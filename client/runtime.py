"""单档案本地运行时。

`GatewayClient`、`AgentLoop`、`LocalStore` 都是同步且非线程安全的,
这里用一把可重入锁把所有调用串行化;FastAPI 的同步路由在线程池中执行,
因此多个请求不会并发触碰这些对象。

一个 Runtime 对应一个档案目录(主档案为 data_dir 根目录,子档案为
data_dir/profiles/<id>)。子档案通过 `shared_session` 复用主档案的登录态,
不单独落令牌。日志与返回值中不出现明文手机号、验证码与令牌。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict
from pathlib import Path

import httpx

from client.conversations import ConversationStore
from client.notifications import ReportStream
from client.onboarding import OnboardingRequired, OnboardingService
from client.reports import ReportService, ReportView
from client.updates import UpdateService
from mhagent.auth_session import AuthSession
from mhagent.cli_setup import DEFAULT_CONSENT_TEXT, mask_phone
from mhagent.consent import ConsentStore
from mhagent.llm.base import LLMError
from mhagent.llm.gateway import GatewayClient, normalize_phone
from mhagent.loop import AgentLoop
from mhagent.mi.report import render_interpretation_report
from mhagent.notifier import Notifier
from mhagent.store.db import LocalStore

logger = logging.getLogger(__name__)


class NotOpened(Exception):
    """本地档案尚未打开。"""


class AlreadyOpened(Exception):
    """本地档案已经打开。"""


class AccountMismatch(Exception):
    """这台设备上已登录过另一个手机号。"""

    def __init__(self, previous_phone: str):
        super().__init__(
            f"这台设备上的本地数据属于原账号(尾号 {mask_phone(previous_phone)[-4:]})"
        )
        self.previous_phone = previous_phone
        self.previous_phone_mask = mask_phone(previous_phone)


def _consent_dict(state) -> dict:
    return asdict(state)


class Runtime:
    """一个档案目录对应一个 Runtime 实例。"""

    def __init__(
        self,
        config: dict,
        store_dir,
        *,
        profile: dict | None = None,
        device_key: str | None = None,
        shared_session: AuthSession | None = None,
        gateway_factory=None,
        notifier_factory=None,
        report_stream_factory=None,
        clock=None,
        report_archive: ReportService | None = None,
        profiles_provider=None,
    ):
        self.config = config
        self.store_dir = Path(store_dir).expanduser()
        self.profile = dict(profile or {"id": "main", "role": "main", "nickname": "我"})
        self._device_key = device_key
        self._shared_session = shared_session
        self._gateway_factory = gateway_factory or self._build_gateway
        self._notifier_factory = notifier_factory or self._build_notifier
        self._report_stream_factory = report_stream_factory
        self._clock = clock
        self._report_archive = report_archive
        self._profiles_provider = profiles_provider
        self._lock = threading.RLock()

        self.store: LocalStore | None = None
        self.session: AuthSession | None = None
        self.consent: ConsentStore | None = None
        self.gateway = None
        self.notifier = None
        self.loop: AgentLoop | None = None
        self.conversations: ConversationStore | None = None
        self.onboarding: OnboardingService | None = None
        self.reports: ReportService | None = None
        self.report_view: ReportView | None = None
        self.report_stream = None
        self.updates: UpdateService | None = None
        self._session_id: str | None = None

    # ---- 组装 ----
    def _build_gateway(self, session: AuthSession):
        gateway_cfg = self.config["gateway"]
        return GatewayClient(
            gateway_cfg["base_url"],
            session,
            model=gateway_cfg["model"],
            timeout=float(gateway_cfg["timeout_seconds"]),
        )

    def _build_notifier(self, consent: ConsentStore, session: AuthSession):
        def token_provider():
            tokens = session.load()
            return tokens.access_token if tokens else ""

        return Notifier(
            self.config["gateway"]["base_url"],
            consent,
            token_provider=token_provider,
        )

    @property
    def is_main(self) -> bool:
        return self.profile.get("role") == "main"

    @property
    def profile_id(self) -> str:
        return str(self.profile.get("id"))

    @property
    def opened(self) -> bool:
        return self.store is not None

    @property
    def logged_in(self) -> bool:
        return bool(self.session and self.session.valid())

    @property
    def phone_mask(self) -> str | None:
        if self.store is None or not self.is_main:
            return None
        phone = self.store.kv_get("account.phone")
        return mask_phone(phone) if phone else None

    def _require(self):
        if self.store is None or self.session is None:
            raise NotOpened("本地档案尚未打开")
        return self.store, self.session

    def open(self) -> dict:
        """打开本地加密库并装配会话、同意书、网关、对话循环。"""
        with self._lock:
            if self.store is not None:
                raise AlreadyOpened("本地档案已打开")
            if not self._device_key:
                raise NotOpened("缺少设备密钥")
            store = LocalStore(self.store_dir, self._device_key)
            try:
                session = self._shared_session or AuthSession(store)
                consent = ConsentStore(store)
                gateway = self._gateway_factory(session)
                notifier = self._notifier_factory(consent, session)
                conversations = ConversationStore(store, clock=self._clock)
                reports = None
                report_view = None
                updates = None
                if self.is_main:
                    reports = ReportService(
                        gateway,
                        store,
                        self.store_dir,
                        clock=self._clock,
                        lock=self._lock,
                        # onboarding 在下方创建;调用发生在提交报告时,闭包按当时的值解析。
                        baseline_provider=lambda: (
                            onboarding.get().get("result") if onboarding else None
                        ),
                    )
                    reports.backfill_memory()
                    reports.refresh_memory()
                    UpdateService.set_content_root(self.store_dir)
                    updates = UpdateService(
                        gateway,
                        store,
                        self.store_dir,
                        lock=self._lock,
                        clock=self._clock,
                    )
                elif self._report_archive is not None:
                    # 子档案不单独归档,只读主档案中分配给自己的报告
                    report_view = ReportView(
                        self._report_archive,
                        self.profile,
                        self._profiles_provider,
                    )
                memory_chars = int(
                    self.config["session"].get("report_memory_chars", 1500)
                )
                report_source = reports or report_view
                onboarding = OnboardingService(
                    store,
                    gateway,
                    self.store_dir,
                    nickname=str(self.profile.get("nickname") or ""),
                    clock=self._clock,
                )
                # 老数据补摘要/记忆;已完成的成员在会话里即可用报告要点。
                onboarding.ensure_interpretation()

                def context_text(question=None):
                    """基础测评记忆优先，剩余预算留给报告记忆。"""
                    parts: list[str] = []
                    baseline = onboarding.memory_text()
                    if baseline:
                        parts.append("【基础测评记忆】\n" + baseline)
                    used = len(parts[0]) if parts else 0
                    if report_source is not None:
                        remainder = memory_chars - used - 2
                        if remainder > 60:
                            extra = report_source.context_text(question, remainder)
                            if extra:
                                parts.append(extra)
                    return "\n\n".join(parts)

                loop = AgentLoop(
                    gateway,
                    store,
                    consent=consent,
                    notifier=notifier,
                    clock=self._clock,
                    max_tokens=int(self.config["session"].get("max_tokens", 1024)),
                    max_history_chars=int(
                        self.config["session"].get("max_context_chars", 2000)
                    ),
                    context_provider=(
                        context_text
                        if (onboarding is not None or report_source is not None)
                        else None
                    ),
                    context_chars=memory_chars,
                )
            except Exception:
                store.close()
                raise
            self.store = store
            self.session = session
            self.consent = consent
            self.gateway = gateway
            self.notifier = notifier
            self.loop = loop
            self.conversations = conversations
            self.onboarding = onboarding
            self.reports = reports
            self.report_view = report_view
            self.updates = updates
            self._session_id = None
            self._ensure_report_stream()
            self._check_updates_async()
            return self.status()

    def close(self) -> None:
        # 先停订阅线程(它会尝试获取同一把锁),再释放本地资源。
        self._stop_report_stream()
        with self._lock:
            for item in (self.gateway, self.notifier):
                close = getattr(item, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if self.store is not None:
                self.store.close()
            self.store = None
            self.session = None
            self.consent = None
            self.gateway = None
            self.notifier = None
            self.loop = None
            self.conversations = None
            self.onboarding = None
            self.reports = None
            self.report_view = None
            self.report_stream = None
            self.updates = None
            self._session_id = None

    # ---- 报告通知 ----
    def _ensure_report_stream(self) -> None:
        """主账号且已登录时保持一条 SSE 长连接。"""
        if not self.is_main or self.gateway is None:
            return
        if self.report_stream is not None or not self.logged_in:
            return
        if not hasattr(self.gateway, "stream_report_events"):
            return
        factory = self._report_stream_factory or (
            lambda gateway, on_event: ReportStream(gateway, on_event)
        )
        stream = factory(self.gateway, self._on_report_event)
        stream.start()
        self.report_stream = stream

    def _stop_report_stream(self) -> None:
        stream = self.report_stream
        self.report_stream = None
        if stream is None:
            return
        stop = getattr(stream, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    def _on_report_event(self, event) -> None:
        if not isinstance(event, dict):
            return
        name = event.get("event")
        if name == "content.updated":
            self._check_updates_async()
            return
        if name not in ("report.created", "report.updated"):
            return
        try:
            self.sync_reports()
        except Exception:
            logger.debug("报告事件触发的同步失败", exc_info=True)

    def _check_updates_async(self) -> None:
        """启动或收到推送时后台检查内容更新,失败不影响主流程。"""
        service = self.updates
        if service is None or not self.logged_in:
            return

        def run() -> None:
            try:
                service.check()
            except Exception:
                logger.debug("检查内容更新失败", exc_info=True)

        threading.Thread(target=run, name="content-update-check", daemon=True).start()

    # ---- 状态 ----
    def status(self) -> dict:
        with self._lock:
            if self.store is None:
                return {
                    "opened": False,
                    "logged_in": False,
                    "phone_mask": None,
                    "consent_version": None,
                    "emergency_authorized": False,
                }
            consent = self.consent.get()
            return {
                "opened": True,
                "logged_in": self.logged_in,
                "phone_mask": self.phone_mask,
                "consent_version": consent.version,
                "emergency_authorized": consent.emergency_authorized,
            }

    # ---- 主账号登录 ----
    def _login_guard(self):
        if not self.is_main:
            raise ValueError("子账号共享主账号登录态,不能单独登录")
        return self._require()

    def send_code(self, phone) -> dict:
        with self._lock:
            self._login_guard()
            self.gateway.send_code(phone)
            return {"ok": True}

    def login_password(self, phone, password, *, force: bool = False) -> dict:
        with self._lock:
            store, session = self._login_guard()
            normalized = normalize_phone(phone)
            secret = "" if password is None else str(password)
            if not secret.strip():
                raise ValueError("密码不能为空")
            tokens = self.gateway.login_password(normalized, secret)
            previous = store.kv_get("account.phone")
            if previous and previous != normalized and not force:
                # 与 CLI 一致:拒绝混用本地数据,并撤销这次刚拿到的令牌
                session.clear()
                raise AccountMismatch(previous)
            store.kv_set("account.phone", normalized)
            self._ensure_report_stream()
            return {
                "is_new": bool(tokens.is_new),
                "phone_mask": mask_phone(normalized),
            }

    def register(self, phone, code, password, *, force: bool = False) -> dict:
        with self._lock:
            store, session = self._login_guard()
            normalized = normalize_phone(phone)
            code_text = "" if code is None else str(code).strip()
            if not code_text:
                raise ValueError("验证码不能为空")
            tokens = self.gateway.register(normalized, code_text, password)
            previous = store.kv_get("account.phone")
            if previous and previous != normalized and not force:
                session.clear()
                raise AccountMismatch(previous)
            store.kv_set("account.phone", normalized)
            self._ensure_report_stream()
            return {
                "is_new": bool(tokens.is_new),
                "phone_mask": mask_phone(normalized),
            }

    def reset_password(self, phone, code, new_password) -> dict:
        with self._lock:
            self._login_guard()
            self.gateway.reset_password(phone, code, new_password)
            return {"ok": True}

    def logout(self) -> dict:
        self._stop_report_stream()
        with self._lock:
            _, session = self._require()
            session.clear()
            return self.status()

    # ---- 同意书与紧急联系人 ----
    def get_consent(self) -> dict:
        with self._lock:
            _, session = self._require()
            local = self.consent.get()
            latest = {
                "version": local.version or "v1",
                "text": DEFAULT_CONSENT_TEXT,
            }
            if session.load() is not None:
                try:
                    data = self.gateway.get_latest_consent()
                except LLMError:
                    data = None
                if data:
                    latest = {
                        "version": str(data.get("version") or latest["version"]),
                        "text": str(data.get("text") or latest["text"]),
                    }
            return {
                "latest": latest,
                "agreed_version": local.version,
                "agreed": local.version == latest["version"],
            }

    def agree_consent(self, version) -> dict:
        with self._lock:
            self._require()
            version_text = "" if version is None else str(version).strip()
            if not version_text:
                raise ValueError("同意书版本不能为空")
            self.gateway.agree_consent(version_text)
            state = self.consent.agree(version_text)
            return _consent_dict(state)

    def get_contact(self) -> dict:
        with self._lock:
            self._require()
            return _consent_dict(self.consent.get())

    def set_contact(self, channel, value, *, authorized: bool = True) -> dict:
        with self._lock:
            self._require()
            state = self.consent.set_emergency_contact(
                str(channel or ""), str(value or ""), authorized=bool(authorized)
            )
            return _consent_dict(state)

    def revoke_contact(self) -> dict:
        with self._lock:
            self._require()
            return _consent_dict(self.consent.revoke_emergency())

    # ---- 会话 ----
    def list_sessions(self) -> dict:
        with self._lock:
            self._require()
            items = self.conversations.list_sessions()
            if not items:
                items = [self.conversations.ensure_primary()]
            return {"items": items}

    def primary_session(self) -> dict:
        with self._lock:
            self._require()
            return self.conversations.ensure_primary()

    def get_session(self, session_id) -> dict:
        with self._lock:
            self._require()
            return self.conversations.get(str(session_id))

    def create_session(self, title="") -> dict:
        """每个档案只有一个会话：返回已存在的唯一会话，不再新建。"""
        with self._lock:
            self._require()
            return self.conversations.ensure_primary()

    def rename_session(self, session_id, title) -> dict:
        with self._lock:
            self._require()
            return self.conversations.rename(str(session_id), title)

    def delete_session(self, session_id) -> dict:
        with self._lock:
            self._require()
            self.conversations.delete(str(session_id))
            return {"ok": True}

    def _switch_session(self, session_id: str, *, force: bool = False) -> None:
        if not force and self._session_id == session_id:
            return
        data = self.conversations.get(session_id)
        self.loop.reset_conversation(data["messages"])
        self._session_id = session_id

    # ---- 测评 ----
    def onboarding_state(self) -> dict:
        with self._lock:
            self._require()
            return self.onboarding.get()

    def onboarding_questionnaire(self) -> dict:
        with self._lock:
            self._require()
            return self.onboarding.questionnaire()

    def save_onboarding_answers(self, answers) -> dict:
        with self._lock:
            self._require()
            return self.onboarding.save_answers(answers)

    def save_onboarding_rankings(self, rankings) -> dict:
        with self._lock:
            self._require()
            return self.onboarding.save_rankings(rankings)

    def attach_gene_report(self, data: bytes, filename: str) -> dict:
        with self._lock:
            self._require()
            return self.onboarding.attach_gene(data, filename)

    def clear_gene_report(self) -> dict:
        with self._lock:
            self._require()
            return self.onboarding.clear_gene()

    def complete_onboarding(self) -> dict:
        with self._lock:
            self._require()
            outcome = self.onboarding.complete()
            self.conversations.ensure_primary()
            return outcome

    def interpretation_report(self, options=None, refresh: bool = False) -> dict:
        with self._lock:
            self._require()
            state = self.onboarding.get()
            result = state.get("result") or {}
            # 旧的报告覆盖与已上传基因报告冲突时，打开页面即自动修复，无需等待手动点击。
            if refresh or result.get("fusion_version") == "REPORT-OVERRIDE":
                self._refresh_gene_basis()
                state = self.onboarding.get()
            if state.get("status") != "completed" or not state.get("result"):
                raise OnboardingRequired("该成员尚未完成基础测评")
            return render_interpretation_report(
                state["result"],
                self.profile,
                options or {},
                gene=state.get("gene"),
                source=(state.get("interpretation") or {}).get("source"),
            )

    def _refresh_gene_basis(self) -> None:
        """生成报告前重新解析该成员已上传的基因报告；无归档时用已保存基因分。"""
        if self.is_main and self.reports is not None:
            found = self.reports.latest_gene_report()
            if found:
                self.onboarding.apply_gene_report(
                    found["scores"],
                    title=found.get("title") or "提交基因报告",
                    report_id=found.get("report_id"),
                    filename=found.get("filename") or "",
                    path=found.get("path") or "",
                )
                return
        state = self.onboarding.get()
        result = state.get("result") or {}
        gene = state.get("gene") or {}
        if gene.get("scores") and result.get("fusion_version") == "REPORT-OVERRIDE":
            self.onboarding.apply_gene_report(
                {"intel": gene["scores"], "ind": {}},
                title=gene.get("title") or gene.get("filename") or "提交基因报告",
                report_id=gene.get("report_id"),
                filename=gene.get("filename") or "",
                path=gene.get("path") or "",
            )

    # ---- 对话与评估 ----
    def chat(self, text, session_id=None) -> dict:
        with self._lock:
            self._require()
            prompt = "" if text is None else str(text).strip()
            if not prompt:
                raise ValueError("消息不能为空")
            self.onboarding.ensure_ready()
            target = "" if session_id is None else str(session_id).strip()
            if not target:
                target = self.conversations.ensure_primary()["session_id"]
            self._switch_session(target, force=self._session_id != target)
            reply = self.loop.handle(prompt)
            snapshot = self.loop.snapshot()
            self.conversations.append(target, "user", prompt)
            self.conversations.append(target, "assistant", reply)
            return {
                "reply": reply,
                "state": snapshot["state"],
                "crisis": snapshot["state"] == "CRISIS",
                "session_id": target,
            }

    def evaluate(self, scale, answers) -> dict:
        with self._lock:
            self._require()
            outcome = self.loop.evaluate_assessment(scale, answers)
            data = asdict(outcome)
            data["state"] = self.loop.snapshot()["state"]
            return data

    # ---- 积分与订单 ----
    def balance(self) -> dict:
        with self._lock:
            self._require()
            return self.gateway.get_balance()

    def packages(self) -> dict:
        with self._lock:
            self._require()
            return {"items": self.gateway.list_packages()}

    def orders(self) -> dict:
        with self._lock:
            self._require()
            return {"items": self.gateway.list_orders()}

    def create_order(self, package_id, channel="mock") -> dict:
        with self._lock:
            self._require()
            if not isinstance(package_id, int) or isinstance(package_id, bool):
                raise ValueError("套餐编号不正确")
            if channel not in ("mock", "manual"):
                raise ValueError("支付渠道必须是 mock 或 manual")
            return self.gateway.create_order(package_id, channel)

    def mock_pay(self, order_id, trade_no=None) -> dict:
        with self._lock:
            self._require()
            return self.gateway.mock_pay(int(order_id), trade_no)

    # ---- 检测报告 ----
    def _report_access(self):
        """主档案用完整归档,子档案用只读视图;未打开返回 None。"""
        if self.store is None:
            raise NotOpened("本地档案尚未打开")
        return self.reports if self.is_main else self.report_view

    def list_reports(self) -> dict:
        with self._lock:
            access = self._report_access()
            if access is None:
                return {"items": [], "unread": 0}
            return {"items": access.list(), "unread": access.unread_count()}

    def sync_reports(self) -> dict:
        with self._lock:
            self._require()
            access = self._report_access()
            if access is None:
                return {"synced": 0, "items": []}
            if not self.is_main:
                try:
                    return access.sync()
                except Exception:
                    # 主档案未登录或网络异常时不影响浏览已归档报告
                    logger.debug("子档案同步报告失败", exc_info=True)
                    return {
                        "synced": 0,
                        "items": access.list(),
                        "unread": access.unread_count(),
                    }
            result = access.sync_pending()
            return {**result, "unread": access.unread_count()}

    def report_file(self, report_id) -> Path:
        with self._lock:
            access = self._report_access()
            if access is None:
                raise KeyError("报告不存在")
            return access.file_path(int(report_id))

    def mark_report_read(self, report_id) -> dict:
        with self._lock:
            access = self._report_access()
            if access is None:
                raise KeyError("报告不存在")
            item = access.mark_read(int(report_id))
            return {"item": item, "unread": access.unread_count()}

    def upload_report(
        self,
        data: bytes,
        filename: str,
        title: str = "",
        revise_interpretation: bool = False,
    ) -> dict:
        """会话内提交检测报告:仅主账号可写,子档案保持只读。

        `revise_interpretation=True` 时把报告分数覆盖到基础测评结果上，
        并重算解读报告摘要与会话记忆（后续对话即以报告为准）。
        """
        with self._lock:
            self._require()
            if not self.is_main or self.reports is None:
                raise ValueError("请在主账号下提交检测报告")
            result = self.reports.upload(data, filename, title)
            if revise_interpretation:
                item = result.get("item") or {}
                scores = result.get("scores") or {}
                report_title = str(item.get("title") or title or "提交报告")
                report_id = item.get("report_id")
                # 能解析出 8 项智能分的报告按基因报告处理：作为基因分参与融合。
                if len((scores.get("intel") or {})) >= 8:
                    revision = self.onboarding.apply_gene_report(
                        scores,
                        title=report_title,
                        report_id=report_id,
                        filename=filename,
                        path=str(item.get("abs_path") or ""),
                    )
                else:
                    revision = self.onboarding.apply_report_scores(
                        scores,
                        title=report_title,
                        report_id=report_id,
                        filename=filename,
                    )
                result["interpretation"] = revision
            return result

    def unread_report_count(self) -> dict:
        with self._lock:
            if self.store is None:
                return {"count": 0}
            access = self._report_access()
            if access is None:
                return {"count": 0}
            return {"count": access.unread_count()}

    # ---- 开发工具 ----
    def dev_sms_code(self, phone) -> str:
        with self._lock:
            self._require()
            normalized = normalize_phone(phone)
            base = str(self.config["gateway"]["base_url"]).rstrip("/")
            try:
                response = httpx.get(
                    f"{base}/dev/sms/last",
                    params={"phone": normalized},
                    timeout=5.0,
                )
            except httpx.HTTPError as exc:
                raise LLMError("开发取码接口不可用") from exc
            if response.status_code == 404:
                raise LLMError("开发取码接口不可用")
            if response.status_code != 200:
                raise LLMError(f"开发取码失败: {response.status_code}")
            try:
                data = response.json()
            except ValueError as exc:
                raise LLMError("开发取码响应格式错误") from exc
            return str(data.get("code", ""))
