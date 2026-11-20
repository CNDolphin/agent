"""本地 FastAPI 服务。

鉴权分两种来源:
- 回环地址(桌面窗口):所有 `/api/*` 需带启动时随机生成的 `X-Local-Token`(注入页面);
- 局域网设备(手机/其他电脑):只放行公开路径,其余需 `X-Device-Token`
  (由子账号用户名 + 密码换取)。

错误统一为 `{"code": ..., "message": ...}`;对话为同步完整回复,不做流式。
"""

from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mhagent.consent import VALID_CHANNELS
from mhagent.llm.base import (
    AuthExpired,
    DuplicateRequest,
    GatewayUnavailable,
    InsufficientCredits,
    LLMError,
)
from mhagent.llm.gateway import (
    AlreadyRegistered,
    CodeInvalid,
    ConsentRequired,
    InvalidPhone,
    PasswordRequired,
    TooFrequent,
    WrongPassword,
)
from mhagent.loop import CRISIS_COPY_TEXT
from mhagent.store.crypto import DecryptError
from mhagent.tools.practices import get_practice, list_practices
from mhagent.tools.scales import SCALE_NAMES, load_questionnaire

from .conversations import ConversationError, SessionLockedError
from .onboarding import GeneExtractError, OnboardingError, OnboardingRequired
from .profiles import (
    DeviceAuthError,
    ProfileConflict,
    ProfileError,
    ProfileNotFound,
    ProfileValidationError,
    RuntimeManager,
    profile_view,
)
from .runtime import AccountMismatch, AlreadyOpened, NotOpened, Runtime
from .updates import UpdateError

LOCAL_TOKEN_HEADER = "X-Local-Token"
DEVICE_TOKEN_HEADER = "X-Device-Token"
PUBLIC_API_PATHS = {"/api/health", "/api/status", "/api/dev-token", "/api/device/login"}
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
WEB_DIST = Path(__file__).resolve().parent / "web" / "dist"
SCALES = ("phq9", "gad7", "pss10")
_CHANNELS = ("mock", "manual")


def _json(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, **extra})


def _text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"缺少参数:{key}")
    return str(value).strip()


def _client_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _is_loopback(request: Request) -> bool:
    return _client_host(request) in LOOPBACK_HOSTS


def create_app(manager: RuntimeManager, local_token: str, dev_mode: bool = False) -> FastAPI:
    app = FastAPI(
        title="mhagent-local",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # ---- 来源分流鉴权 ----
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if _is_loopback(request):
            if path in PUBLIC_API_PATHS:
                return await call_next(request)
            if request.headers.get(LOCAL_TOKEN_HEADER) != local_token:
                return _json(401, "unauthorized", "本地令牌无效")
            return await call_next(request)
        # 局域网设备:公开路径之外一律要求设备令牌。
        if path in PUBLIC_API_PATHS:
            return await call_next(request)
        try:
            request.state.profile_id = manager.profile_for_device_token(
                request.headers.get(DEVICE_TOKEN_HEADER, "")
            )
        except DeviceAuthError as exc:
            return _json(401, "device_auth_required", str(exc))
        return await call_next(request)

    def current(request: Request) -> Runtime:
        if _is_loopback(request):
            return manager.runtime_for()
        return manager.runtime_for(request.state.profile_id)

    def desktop_only(request: Request):
        if not _is_loopback(request):
            return _json(403, "desktop_only", "该操作仅限桌面端")
        return None

    def updates_service(request: Request):
        runtime = current(request)
        if runtime.updates is not None:
            return runtime.updates
        main = manager.main()
        if main.updates is None:
            raise UpdateError("更新服务尚未就绪,请先登录主账号")
        return main.updates

    # ---- 错误映射 ----
    @app.exception_handler(NotOpened)
    def _not_opened(request, exc):
        return _json(401, "not_opened", str(exc))

    @app.exception_handler(AlreadyOpened)
    def _already_opened(request, exc):
        return _json(409, "already_opened", str(exc))

    @app.exception_handler(AccountMismatch)
    def _account_mismatch(request, exc):
        return _json(
            409,
            "account_mismatch",
            str(exc),
            previous_phone_mask=exc.previous_phone_mask,
        )

    @app.exception_handler(ProfileValidationError)
    def _profile_invalid(request, exc):
        return _json(400, "invalid_request", str(exc))

    @app.exception_handler(ProfileConflict)
    def _profile_conflict(request, exc):
        return _json(409, "profile_conflict", str(exc))

    @app.exception_handler(ProfileNotFound)
    def _profile_not_found(request, exc):
        return _json(404, "profile_not_found", str(exc))

    @app.exception_handler(SessionLockedError)
    def _session_locked(request, exc):
        return _json(400, "session_locked", str(exc))

    @app.exception_handler(ConversationError)
    def _conversation_error(request, exc):
        return _json(404, "session_not_found", str(exc))

    @app.exception_handler(OnboardingRequired)
    def _onboarding_required(request, exc):
        return _json(409, "onboarding_required", str(exc))

    @app.exception_handler(UpdateError)
    def _update_error(request, exc):
        return _json(400, "update_failed", str(exc))

    @app.exception_handler(GeneExtractError)
    def _gene_extract(request, exc):
        return _json(422, "gene_unrecognized", str(exc))

    @app.exception_handler(OnboardingError)
    def _onboarding_invalid(request, exc):
        return _json(400, "invalid_request", str(exc))

    @app.exception_handler(DeviceAuthError)
    def _device_auth(request, exc):
        return _json(401, "device_auth_required", str(exc))

    @app.exception_handler(ProfileError)
    def _profile_error(request, exc):
        return _json(400, "profile_error", str(exc))

    @app.exception_handler(DecryptError)
    def _decrypt_error(request, exc):
        return _json(400, "invalid_passphrase", "旧口令错误,数据未被修改")

    @app.exception_handler(AuthExpired)
    def _auth_expired(request, exc):
        return _json(401, "auth_expired", "登录已过期,请重新登录")

    @app.exception_handler(WrongPassword)
    def _wrong_password(request, exc):
        return _json(401, "wrong_password", "手机号或密码错误")

    @app.exception_handler(PasswordRequired)
    def _password_required(request, exc):
        return _json(409, "password_required", str(exc))

    @app.exception_handler(AlreadyRegistered)
    def _already_registered(request, exc):
        return _json(409, "already_registered", "该手机号已注册,请直接登录")

    @app.exception_handler(InsufficientCredits)
    def _insufficient(request, exc):
        return _json(402, "insufficient_credits", "积分不足,可购买套餐获取积分")

    @app.exception_handler(ConsentRequired)
    def _consent_required(request, exc):
        return _json(403, "consent_required", "需要先签署最新同意书")

    @app.exception_handler(DuplicateRequest)
    def _duplicate(request, exc):
        return _json(409, "duplicate_request", "这条消息已经处理过了")

    @app.exception_handler(TooFrequent)
    def _too_frequent(request, exc):
        wait = exc.wait_seconds or 60
        response = _json(429, "too_frequent", "操作过于频繁,请稍后再试")
        response.headers["Retry-After"] = str(wait)
        return response

    @app.exception_handler(InvalidPhone)
    def _invalid_phone(request, exc):
        return _json(400, "invalid_phone", str(exc))

    @app.exception_handler(CodeInvalid)
    def _invalid_code(request, exc):
        return _json(400, "invalid_code", str(exc))

    @app.exception_handler(GatewayUnavailable)
    def _gateway_unavailable(request, exc):
        return _json(502, "gateway_unavailable", "服务暂时不可用,请稍后重试")

    @app.exception_handler(LLMError)
    def _llm_error(request, exc):
        return _json(502, "gateway_unavailable", "服务暂时不可用,请稍后重试")

    @app.exception_handler(ValueError)
    def _bad_request(request, exc):
        return _json(400, "invalid_request", str(exc))

    @app.exception_handler(KeyError)
    def _not_found(request, exc):
        return _json(404, "not_found", "内容不存在")

    @app.exception_handler(StarletteHTTPException)
    def _http_error(request, exc):
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _json(exc.status_code, code, str(exc.detail))

    # ---- 基础 ----
    @app.get("/api/health")
    def health():
        return {"ok": True, "lan_enabled": manager.lan_enabled}

    @app.get("/api/dev-token")
    def dev_token(request: Request):
        if not dev_mode:
            return _json(404, "not_found", "开发接口不可用")
        if not _is_loopback(request):
            return _json(403, "desktop_only", "该操作仅限桌面端")
        return {"token": local_token}

    @app.get("/api/status")
    def status(request: Request):
        if _is_loopback(request):
            return {
                **manager.status(),
                "device_mode": "desktop",
                "dev_mode": dev_mode,
            }
        if manager.legacy_required:
            return {"device_mode": "lan", "lan_enabled": True, "legacy_required": True}
        try:
            profile_id = manager.profile_for_device_token(request.headers.get(DEVICE_TOKEN_HEADER, ""))
        except DeviceAuthError:
            return {
                "device_mode": "lan",
                "lan_enabled": True,
                "legacy_required": False,
                "logged_in": False,
                "active_profile": None,
                "profiles": [],
                "consent_version": None,
                "emergency_authorized": False,
            }
        runtime = manager.runtime_for(profile_id)
        state = runtime.status()
        return {
            "device_mode": "lan",
            "lan_enabled": True,
            "legacy_required": False,
            "logged_in": True,
            "active_profile": profile_view(manager.profiles.raw(profile_id)),
            "profiles": [],
            "consent_version": state["consent_version"],
            "emergency_authorized": state["emergency_authorized"],
        }

    # ---- 局域网设备登录 ----
    @app.post("/api/device/login")
    def device_login(payload: dict = Body(...)):
        return manager.device_login(_text(payload, "username"), _text(payload, "password"))

    # ---- 旧版数据迁移 ----
    @app.post("/api/legacy/migrate")
    def migrate(request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.migrate_legacy(payload.get("passphrase"))

    # ---- 主账号登录 ----
    @app.post("/api/auth/send-code")
    def send_code(request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.send_code(_text(payload, "phone"))

    @app.post("/api/auth/login")
    def login(request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.login_password(
            _text(payload, "phone"),
            _text(payload, "password"),
            force=bool(payload.get("force")),
        )

    @app.post("/api/auth/register")
    def register(request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.register(
            _text(payload, "phone"),
            _text(payload, "code"),
            _text(payload, "password"),
            force=bool(payload.get("force")),
        )

    @app.post("/api/auth/reset-password")
    def reset_password(request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.reset_password(
            _text(payload, "phone"),
            _text(payload, "code"),
            _text(payload, "new_password"),
        )

    @app.post("/api/auth/logout")
    def logout(request: Request):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.logout()

    # ---- 档案管理(仅桌面端) ----
    @app.get("/api/profiles")
    def profiles(request: Request):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return {"items": manager.list_profiles()}

    @app.post("/api/profiles")
    def create_profile(request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.create_profile(
            _text(payload, "nickname"),
            _text(payload, "username"),
            _text(payload, "password"),
            note=str(payload.get("note") or ""),
            age_range=str(payload.get("age_range") or ""),
        )

    @app.patch("/api/profiles/{profile_id}")
    def update_profile(profile_id: str, request: Request, payload: dict = Body(...)):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        fields = {
            key: payload[key]
            for key in ("nickname", "note", "age_range", "username", "password", "status")
            if key in payload
        }
        return manager.update_profile(profile_id, **fields)

    @app.delete("/api/profiles/{profile_id}")
    def delete_profile(profile_id: str, request: Request):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        manager.delete_profile(profile_id)
        return {"ok": True}

    @app.post("/api/profiles/{profile_id}/activate")
    def activate_profile(profile_id: str, request: Request):
        denied = desktop_only(request)
        if denied is not None:
            return denied
        return manager.activate(profile_id)

    # ---- 会话 ----
    @app.get("/api/sessions")
    def list_sessions(request: Request):
        return current(request).list_sessions()

    @app.post("/api/sessions")
    def create_session(request: Request, payload: dict = Body(default={})):
        return current(request).create_session(str(payload.get("title") or ""))

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, request: Request):
        return current(request).get_session(session_id)

    @app.patch("/api/sessions/{session_id}")
    def rename_session(session_id: str, request: Request, payload: dict = Body(...)):
        return current(request).rename_session(session_id, _text(payload, "title"))

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str, request: Request):
        return current(request).delete_session(session_id)

    # ---- 入会话前测评 ----
    @app.get("/api/onboarding")
    def onboarding_state(request: Request):
        return current(request).onboarding_state()

    @app.get("/api/onboarding/questionnaire")
    def onboarding_questionnaire(request: Request):
        return current(request).onboarding_questionnaire()

    @app.put("/api/onboarding/answers")
    def save_onboarding_answers(request: Request, payload: dict = Body(...)):
        return current(request).save_onboarding_answers(payload.get("answers") or {})

    @app.put("/api/onboarding/rankings")
    def save_onboarding_rankings(request: Request, payload: dict = Body(...)):
        return current(request).save_onboarding_rankings(payload)

    @app.post("/api/onboarding/gene")
    def upload_gene(request: Request, payload: dict = Body(...)):
        filename = _text(payload, "filename")
        content = str(payload.get("content") or "")
        if not content:
            raise ValueError("缺少参数:content")
        try:
            data = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("文件内容不是合法的 base64") from exc
        gene = current(request).attach_gene_report(data, filename)
        return {"gene": gene}

    @app.delete("/api/onboarding/gene")
    def clear_gene(request: Request):
        return current(request).clear_gene_report()

    @app.post("/api/onboarding/complete")
    def complete_onboarding(request: Request):
        return current(request).complete_onboarding()

    # ---- 同意书与联系人 ----
    @app.get("/api/consents/latest")
    def latest_consent(request: Request):
        return current(request).get_consent()

    @app.post("/api/consents/agree")
    def agree_consent(request: Request, payload: dict = Body(...)):
        state = current(request).agree_consent(_text(payload, "version"))
        return {"ok": True, "consent": state}

    @app.get("/api/contact")
    def get_contact(request: Request):
        return current(request).get_contact()

    @app.post("/api/contact")
    def set_contact(request: Request, payload: dict = Body(...)):
        channel = _text(payload, "channel")
        if channel not in VALID_CHANNELS:
            raise ValueError("渠道必须是 sms 或 email")
        return current(request).set_contact(
            channel,
            _text(payload, "value"),
            authorized=bool(payload.get("authorized", True)),
        )

    @app.delete("/api/contact")
    def revoke_contact(request: Request):
        return current(request).revoke_contact()

    # ---- 对话 ----
    @app.post("/api/chat")
    def chat(request: Request, payload: dict = Body(...)):
        return current(request).chat(
            _text(payload, "text"),
            session_id=payload.get("session_id"),
        )

    # ---- 量表 ----
    @app.get("/api/scales")
    def list_scales():
        items = []
        for scale in SCALES:
            questionnaire = load_questionnaire(scale)
            items.append(
                {
                    "id": scale,
                    "name": SCALE_NAMES.get(scale, scale),
                    "version": questionnaire.version,
                    "available": questionnaire.available,
                    "item_count": len(questionnaire.items),
                }
            )
        return {"items": items}

    @app.get("/api/scales/{scale}")
    def scale_detail(scale: str):
        questionnaire = load_questionnaire(scale)
        return {
            "id": questionnaire.scale,
            "name": SCALE_NAMES.get(scale, scale),
            "version": questionnaire.version,
            "intro": questionnaire.intro,
            "options": list(questionnaire.options),
            "items": list(questionnaire.items),
            "available": questionnaire.available,
        }

    @app.post("/api/scales/{scale}/submit")
    def submit_scale(scale: str, request: Request, payload: dict = Body(...)):
        return current(request).evaluate(scale, payload.get("answers"))

    # ---- 练习 ----
    @app.get("/api/practices")
    def practices():
        items = []
        for practice_id in list_practices():
            detail = get_practice(practice_id)
            items.append(
                {
                    "id": practice_id,
                    "name": detail.get("name", practice_id),
                    "summary": detail.get("summary", ""),
                    "repeat": detail.get("repeat", 1),
                    "duration_seconds": detail.get("duration_seconds", 0),
                }
            )
        return {"items": items}

    @app.get("/api/practices/{practice_id}")
    def practice_detail(practice_id: str):
        detail = get_practice(practice_id)
        return {"id": practice_id, **detail}

    # ---- 积分与订单 ----
    @app.get("/api/credits")
    def credits(request: Request):
        return current(request).balance()

    @app.get("/api/packages")
    def packages(request: Request):
        return current(request).packages()

    @app.get("/api/orders")
    def orders(request: Request):
        return current(request).orders()

    @app.post("/api/orders")
    def create_order(request: Request, payload: dict = Body(...)):
        channel = str(payload.get("channel") or "mock")
        if channel not in _CHANNELS:
            raise ValueError("支付渠道必须是 mock 或 manual")
        return current(request).create_order(payload.get("package_id"), channel)

    @app.post("/api/orders/{order_id}/mock-pay")
    def mock_pay(order_id: int, request: Request):
        if not dev_mode:
            return _json(404, "not_found", "开发接口不可用")
        return current(request).mock_pay(order_id)

    # ---- 检测报告 ----
    @app.get("/api/reports")
    def list_reports(request: Request):
        return current(request).list_reports()

    @app.get("/api/reports/unread-count")
    def report_unread(request: Request):
        return current(request).unread_report_count()

    @app.post("/api/reports/sync")
    def sync_reports(request: Request):
        return current(request).sync_reports()

    @app.get("/api/reports/{report_id}/file")
    def report_file(report_id: int, request: Request):
        path = current(request).report_file(report_id)
        return FileResponse(path, filename=path.name)

    @app.post("/api/reports/{report_id}/read")
    def report_read(report_id: int, request: Request):
        return current(request).mark_report_read(report_id)

    # ---- 在线更新 ----
    @app.get("/api/updates")
    def updates_status(request: Request):
        return updates_service(request).status()

    @app.post("/api/updates/check")
    def updates_check(request: Request):
        return updates_service(request).check()

    @app.post("/api/updates/{release_id}/download")
    def updates_download(release_id: int, request: Request):
        return updates_service(request).download(release_id)

    # ---- 危机支持 ----
    @app.get("/api/crisis")
    def crisis():
        return {
            "hotlines": [
                {"name": "心理援助热线", "number": "12356"},
                {"name": "急救电话", "number": "120"},
            ],
            "message": (
                "如果你现在有伤害自己的念头,请立即拨打 12356 或 120,"
                "或前往最近的急诊;尽量让信任的人陪着你。"
            ),
            "copy_text": CRISIS_COPY_TEXT,
        }

    # ---- 开发工具 ----
    @app.get("/api/dev/sms-code")
    def dev_sms_code(request: Request, phone: str = Query(...)):
        if not dev_mode:
            return _json(404, "not_found", "开发接口不可用")
        if not _is_loopback(request):
            return _json(403, "desktop_only", "该操作仅限桌面端")
        return {"code": manager.dev_sms_code(phone)}

    # ---- 静态资源 ----
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_ui(full_path: str, request: Request):
        if full_path.startswith("api/"):
            return _json(404, "not_found", "接口不存在")
        if ".." not in Path(full_path).parts:
            candidate = (WEB_DIST / full_path).resolve()
            if full_path and WEB_DIST in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        index = WEB_DIST / "index.html"
        if not index.exists():
            return HTMLResponse(
                "<h1>前端尚未构建</h1><p>请在 client/web 执行 npm run build。</p>",
                status_code=503,
            )
        html = index.read_text(encoding="utf-8")
        if _is_loopback(request):
            # 局域网页面不注入本地令牌:设备需用子账号密码换取设备令牌。
            script = (
                "<script>window.__LOCAL_TOKEN__="
                + json.dumps(local_token)
                + ";</script>"
            )
            if "</head>" in html:
                html = html.replace("</head>", script + "</head>", 1)
            else:
                html = script + html
        return HTMLResponse(html)

    return app
