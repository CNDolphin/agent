"""后端网关客户端。

契约见 `docs/superpowers/plans/00-overview-and-contracts.md` 第 3 节:
Bearer 令牌、`X-Request-Id` 幂等、402/401/429/409/502 映射、刷新重试一次、
SSE 流式解析。日志与异常信息中不得出现消息正文、联系人或令牌。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Iterator
from urllib.parse import unquote

import httpx

from mhagent.auth_session import AuthSession, TokenPair
from mhagent.llm.base import (
    AuthExpired,
    ChatResult,
    DuplicateRequest,
    GatewayUnavailable,
    InsufficientCredits,
    LLMError,
)

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class InvalidPhone(LLMError):
    """本地手机号格式校验失败。"""


class CodeInvalid(LLMError):
    """验证码错误或已失效(40102)。"""


class TooFrequent(LLMError):
    """触发限流(429)。"""

    def __init__(self, message: str = "操作过于频繁,请稍后再试", wait_seconds: int | None = None):
        super().__init__(message)
        self.wait_seconds = wait_seconds


class ConsentRequired(LLMError):
    """未签署最新同意书(403)。"""


class WrongPassword(LLMError):
    """手机号或密码错误(40104)。"""


class PasswordRequired(LLMError):
    """该账号尚未设置密码,需先用验证码完成首次设置(40105)。"""


class AlreadyRegistered(LLMError):
    """该手机号已注册(40902)。"""


def normalize_phone(phone: str) -> str:
    """本地规范化并校验中国大陆手机号;不合法直接拒绝,不发请求。"""
    if not isinstance(phone, str):
        raise InvalidPhone("手机号格式不正确")
    value = phone.strip().replace(" ", "").replace("-", "")
    if value.startswith("+86"):
        value = value[3:]
    elif value.startswith("86") and len(value) == 13:
        value = value[2:]
    if not PHONE_RE.match(value):
        raise InvalidPhone("手机号格式不正确,请输入中国大陆 11 位手机号")
    return value


def _safe_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _content_disposition_name(value: str | None) -> str:
    """从 Content-Disposition 解析下载文件名,优先 RFC 5987 编码形式。"""
    if not value:
        return ""
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if encoded:
        return unquote(encoded.group(1))
    plain = re.search(r'filename="?([^";]+)"?', value, re.IGNORECASE)
    return plain.group(1) if plain else ""


def _iter_sse(response: httpx.Response) -> Iterator[tuple[str, str]]:
    event = ""
    data_lines: list[str] = []

    def flush():
        nonlocal event, data_lines
        if data_lines:
            payload = (event or "message", "\n".join(data_lines))
            event = ""
            data_lines = []
            return payload
        event = ""
        data_lines = []
        return None

    for line in response.iter_lines():
        if line == "":
            item = flush()
            if item:
                yield item
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())
    item = flush()
    if item:
        yield item


class GatewayClient:
    """后端模型网关的同步客户端。"""

    def __init__(
        self,
        base_url: str,
        session: AuthSession,
        *,
        model: str = "deepseek-flash",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.model = model
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)
        self.last_stream_result: ChatResult | None = None

    # ---- 内部工具 ----
    def _headers(self, request_id: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if request_id:
            headers["X-Request-Id"] = request_id
        tokens = self.session.load()
        if not tokens or not tokens.access_token:
            raise AuthExpired("未登录或登录已过期")
        headers["Authorization"] = f"Bearer {tokens.access_token}"
        return headers

    def _wait_seconds(self, response: httpx.Response) -> int | None:
        for key in ("Retry-After", "retry-after"):
            raw = response.headers.get(key)
            if raw:
                try:
                    return int(float(raw))
                except ValueError:
                    pass
        data = _safe_json(response)
        for key in ("retry_after", "wait_seconds"):
            if key in data:
                try:
                    return int(data[key])
                except (TypeError, ValueError):
                    pass
        return None

    def _raise_common(self, response: httpx.Response) -> None:
        status = response.status_code
        code = _safe_json(response).get("code")
        if status == 401 or code in (40101, 40102):
            raise AuthExpired("登录已过期,请重新登录")
        if status == 402 or code == 40201:
            raise InsufficientCredits("积分不足")
        if status == 403 or code == 40301:
            raise ConsentRequired("需要先签署最新同意书")
        if status == 429 or code == 42901:
            raise TooFrequent(wait_seconds=self._wait_seconds(response))
        if status == 409 or code == 40901:
            data = _safe_json(response)
            raise DuplicateRequest(
                "该请求已结算",
                cost=data.get("cost"),
                balance=data.get("balance"),
            )
        raise GatewayUnavailable(f"网关返回异常状态 {status}")

    # ---- 认证 ----
    def send_code(self, phone: str) -> None:
        phone = normalize_phone(phone)
        response = self._client.post("/auth/sms/send", json={"phone": phone})
        if response.status_code in (200, 204):
            return
        if response.status_code == 429:
            raise TooFrequent(wait_seconds=self._wait_seconds(response))
        if response.status_code == 400:
            raise InvalidPhone("手机号格式不正确")
        raise GatewayUnavailable(f"发送验证码失败: {response.status_code}")

    def login(self, phone: str, code: str) -> TokenPair:
        phone = normalize_phone(phone)
        response = self._client.post("/auth/login", json={"phone": phone, "code": code})
        if response.status_code in (200, 201):
            return self._save_tokens(_safe_json(response))
        if response.status_code == 429:
            raise TooFrequent(wait_seconds=self._wait_seconds(response))
        if response.status_code in (400, 401) or _safe_json(response).get("code") == 40102:
            raise CodeInvalid("验证码错误或已失效")
        raise GatewayUnavailable(f"登录失败: {response.status_code}")

    def login_password(self, phone: str, password: str) -> TokenPair:
        """手机号 + 密码登录。"""
        phone = normalize_phone(phone)
        response = self._client.post(
            "/auth/login/password", json={"phone": phone, "password": password}
        )
        code = _safe_json(response).get("code")
        if response.status_code in (200, 201):
            return self._save_tokens(_safe_json(response))
        if response.status_code == 429:
            raise TooFrequent(wait_seconds=self._wait_seconds(response))
        if code == 40105:
            raise PasswordRequired("该账号尚未设置密码,请先用手机验证码完成首次设置")
        if response.status_code in (400, 401) or code == 40104:
            raise WrongPassword("手机号或密码错误")
        raise GatewayUnavailable(f"登录失败: {response.status_code}")

    def register(self, phone: str, code: str, password: str) -> TokenPair:
        """首次注册:手机号 + 验证码 + 密码。"""
        phone = normalize_phone(phone)
        response = self._client.post(
            "/auth/register", json={"phone": phone, "code": code, "password": password}
        )
        body = _safe_json(response)
        if response.status_code in (200, 201):
            return self._save_tokens(body)
        if response.status_code == 429:
            raise TooFrequent(wait_seconds=self._wait_seconds(response))
        if body.get("code") == 40902:
            raise AlreadyRegistered("该手机号已注册,请直接登录")
        if body.get("code") == 40102 or response.status_code == 401:
            raise CodeInvalid("验证码错误或已失效")
        if response.status_code == 400:
            raise ValueError(str(body.get("message") or "注册信息不正确"))
        raise GatewayUnavailable(f"注册失败: {response.status_code}")

    def reset_password(self, phone: str, code: str, new_password: str) -> None:
        """验证码重置密码。"""
        phone = normalize_phone(phone)
        response = self._client.post(
            "/auth/password/reset",
            json={"phone": phone, "code": code, "new_password": new_password},
        )
        if response.status_code in (200, 204):
            return
        body = _safe_json(response)
        if response.status_code == 429:
            raise TooFrequent(wait_seconds=self._wait_seconds(response))
        if body.get("code") == 40102 or response.status_code == 401:
            raise CodeInvalid("验证码错误或已失效")
        if response.status_code == 400:
            raise ValueError(str(body.get("message") or "新密码不符合要求"))
        raise GatewayUnavailable(f"重置密码失败: {response.status_code}")

    def _save_tokens(self, data: dict, *, default_refresh: str = "") -> TokenPair:
        tokens = TokenPair(
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token", default_refresh)),
            expires_in=int(data.get("expires_in", 3600)),
            is_new=bool(data.get("is_new", False)),
        )
        if not tokens.access_token:
            raise GatewayUnavailable("登录响应缺少 access_token")
        self.session.save(tokens)
        return tokens

    def refresh(self) -> TokenPair:
        tokens = self.session.load()
        if not tokens or not tokens.refresh_token:
            raise AuthExpired("缺少 refresh_token,请重新登录")
        response = self._client.post("/auth/refresh", json={"refresh_token": tokens.refresh_token})
        if response.status_code in (200, 201):
            data = _safe_json(response)
            data.pop("is_new", None)
            return self._save_tokens(data, default_refresh=tokens.refresh_token)
        raise AuthExpired("登录已过期,请重新登录")

    # ---- 同意书 ----
    def get_latest_consent(self) -> dict:
        response = self._client.get("/consent/latest", headers=self._headers())
        if response.status_code != 200:
            self._raise_common(response)
        return _safe_json(response)

    def agree_consent(self, version: str) -> None:
        response = self._client.post(
            "/consent", json={"version": version}, headers=self._headers()
        )
        if response.status_code not in (200, 204):
            self._raise_common(response)

    # ---- 对话 ----
    def _chat_body(self, messages: list[dict], max_tokens: int, stream: bool) -> dict:
        # 只发送契约允许的字段,不传 thinking 等后端专属配置
        return {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    def chat(self, messages: list[dict], *, max_tokens: int = 1024) -> ChatResult:
        request_id = str(uuid.uuid4())
        body = self._chat_body(messages, max_tokens, False)
        retried = False
        refreshed = False
        while True:
            try:
                response = self._client.post(
                    "/llm/chat", json=body, headers=self._headers(request_id)
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if retried:
                    raise GatewayUnavailable("模型服务暂时不可用,请稍后重试") from exc
                retried = True
                logger.debug("gateway transport error, retrying request_id=%s", request_id)
                continue

            status = response.status_code
            if status == 401:
                if refreshed:
                    raise AuthExpired("登录已过期,请重新登录")
                self.refresh()
                refreshed = True
                continue
            if status == 502:
                if retried:
                    raise GatewayUnavailable("模型服务暂时不可用,请稍后重试")
                retried = True
                continue
            if status != 200:
                self._raise_common(response)

            data = _safe_json(response)
            usage = data.get("usage") or {}
            return ChatResult(
                content=str(data.get("content", "")),
                input_hit=int(usage.get("input_hit", 0) or 0),
                input_miss=int(usage.get("input_miss", 0) or 0),
                output=int(usage.get("output", 0) or 0),
                cost=int(data.get("cost", 0) or 0),
                balance=int(data.get("balance", 0) or 0),
                low_balance=bool(data.get("low_balance", False)),
            )

    def chat_stream(self, messages: list[dict], *, max_tokens: int = 1024) -> Iterator[str]:
        request_id = str(uuid.uuid4())
        body = self._chat_body(messages, max_tokens, True)
        retried = False
        refreshed = False
        while True:
            try:
                with self._client.stream(
                    "POST", "/llm/chat", json=body, headers=self._headers(request_id)
                ) as response:
                    status = response.status_code
                    if status == 401:
                        response.read()
                        if refreshed:
                            raise AuthExpired("登录已过期,请重新登录")
                        self.refresh()
                        refreshed = True
                        continue
                    if status == 502:
                        response.read()
                        if retried:
                            raise GatewayUnavailable("模型服务暂时不可用,请稍后重试")
                        retried = True
                        continue
                    if status != 200:
                        response.read()
                        self._raise_common(response)
                    yield from self._parse_stream(response)
                    return
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if retried:
                    raise GatewayUnavailable("模型服务暂时不可用,请稍后重试") from exc
                retried = True
                continue

    def _parse_stream(self, response: httpx.Response) -> Iterator[str]:
        parts: list[str] = []
        for event, data in _iter_sse(response):
            if event == "delta":
                payload = json.loads(data) if data else {}
                text = str(payload.get("text", ""))
                parts.append(text)
                yield text
            elif event == "done":
                payload = json.loads(data) if data else {}
                usage = payload.get("usage") or {}
                self.last_stream_result = ChatResult(
                    content="".join(parts),
                    input_hit=int(usage.get("input_hit", 0) or 0),
                    input_miss=int(usage.get("input_miss", 0) or 0),
                    output=int(usage.get("output", 0) or 0),
                    cost=int(payload.get("cost", 0) or 0),
                    balance=int(payload.get("balance", 0) or 0),
                    low_balance=bool(payload.get("low_balance", False)),
                )
            elif event == "error":
                payload = json.loads(data) if data else {}
                raise GatewayUnavailable(str(payload.get("message", "模型服务异常")))

    # ---- 账户与套餐 ----
    def _account_request(
        self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None
    ) -> httpx.Response:
        """带登录态的请求:401 时刷新令牌并重试一次。"""
        refreshed = False
        while True:
            response = self._client.request(
                method,
                path,
                json=json_body,
                params=params,
                headers=self._headers(),
            )
            if response.status_code == 401 and not refreshed:
                self.refresh()
                refreshed = True
                continue
            if response.status_code not in (200, 204):
                self._raise_common(response)
            return response

    def get_balance(self) -> dict:
        data = _safe_json(self._account_request("GET", "/credits/balance"))
        return {
            "balance": int(data.get("balance", 0) or 0),
            "held": int(data.get("held", 0) or 0),
            "available": int(data.get("available", 0) or 0),
        }

    def list_packages(self) -> list[dict]:
        data = _safe_json(self._account_request("GET", "/packages"))
        items = data.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    def create_order(self, package_id: int, channel: str) -> dict:
        data = _safe_json(
            self._account_request(
                "POST",
                "/orders",
                json_body={"package_id": int(package_id), "channel": channel},
            )
        )
        return {
            "order_id": int(data.get("order_id", 0) or 0),
            "status": str(data.get("status", "")),
            "pay_params": data.get("pay_params") or {},
        }

    def list_orders(self) -> list[dict]:
        data = _safe_json(self._account_request("GET", "/orders"))
        items = data.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    def mock_pay(self, order_id: int, trade_no: str | None = None) -> dict:
        """模拟支付回调(仅开发工具使用,生产环境不应调用)。"""
        body = {
            "order_id": int(order_id),
            "trade_no": trade_no or f"mock-{uuid.uuid4().hex[:16]}",
            "status": "success",
        }
        response = self._client.post("/pay/callback/mock", json=body)
        if response.status_code != 200:
            self._raise_common(response)
        return _safe_json(response)

    # ---- 检测报告 ----
    def list_pending_reports(self) -> list[dict]:
        """拉取尚未下载的报告(服务端同时标记为已通知)。"""
        data = _safe_json(self._account_request("GET", "/reports/pending"))
        items = data.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    def download_report(self, report_id: int) -> tuple[str, bytes, str]:
        """下载报告当前版本,返回 (文件名, 内容, Content-Type)。"""
        response = self._account_request("GET", f"/reports/{int(report_id)}/download")
        disposition = response.headers.get("Content-Disposition") or response.headers.get(
            "content-disposition"
        )
        filename = _content_disposition_name(disposition)
        content_type = response.headers.get("Content-Type") or "application/octet-stream"
        return filename, response.content, content_type

    def mark_report_read(self, report_id: int) -> None:
        self._account_request("POST", f"/reports/{int(report_id)}/read")

    # ---- 内容更新 ----
    def latest_contents(self, platform: str = "macos") -> list[dict]:
        """获取各类内容的最新已发布版本。"""
        data = _safe_json(
            self._account_request("GET", "/contents/latest", params={"platform": platform})
        )
        items = data.get("items") or []
        return [item for item in items if isinstance(item, dict)]

    def download_content(self, release_id: int) -> tuple[str, bytes, str, str]:
        """下载内容包,返回 (文件名, 内容, SHA256, 版本)。"""
        response = self._account_request("GET", f"/contents/{int(release_id)}/download")
        disposition = response.headers.get("Content-Disposition") or response.headers.get(
            "content-disposition"
        )
        filename = _content_disposition_name(disposition)
        digest = response.headers.get("X-Content-SHA256") or ""
        version = response.headers.get("X-Content-Version") or ""
        return filename, response.content, digest, version

    def stream_report_events(self) -> Iterator[dict]:
        """订阅报告事件 SSE;连接结束或被关闭时返回/抛错。"""
        refreshed = False
        while True:
            try:
                with self._client.stream(
                    "GET",
                    "/notifications/stream",
                    headers=self._headers(),
                    timeout=httpx.Timeout(30.0, connect=10.0),
                ) as response:
                    if response.status_code == 401:
                        response.read()
                        if refreshed:
                            raise AuthExpired("登录已过期,请重新登录")
                        self.refresh()
                        refreshed = True
                        continue
                    if response.status_code != 200:
                        response.read()
                        self._raise_common(response)
                    yield from self._parse_report_stream(response)
                    return
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise GatewayUnavailable("报告通知连接中断") from exc

    def _parse_report_stream(self, response: httpx.Response) -> Iterator[dict]:
        for event, data in _iter_sse(response):
            payload: dict = {}
            if data:
                try:
                    parsed = json.loads(data)
                    payload = parsed if isinstance(parsed, dict) else {"value": parsed}
                except ValueError:
                    payload = {"raw": data}
            yield {"event": event, "data": payload}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
