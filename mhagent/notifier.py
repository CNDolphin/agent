"""紧急通知:仅在用户已单独授权时,把联系方式随请求发给后端。

后端发送后不落库;本地也不记录发送内容。日志中禁止出现联系人信息。
"""

from __future__ import annotations

import httpx

from mhagent.consent import ConsentStore

DEFAULT_TEMPLATE_ID = "crisis_contact_v1"


class NotifyError(Exception):
    """通知未授权、发送失败或配置缺失。"""


class Notifier:
    def __init__(
        self,
        base_url: str,
        consent: ConsentStore,
        *,
        http_client: httpx.Client | None = None,
        template_id: str = DEFAULT_TEMPLATE_ID,
        nickname: str = "用户",
        token_provider=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.consent = consent
        self.template_id = template_id
        self.nickname = nickname
        self.token_provider = token_provider
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=15)

    def _headers(self) -> dict:
        if self.token_provider is None:
            return {}
        token = self.token_provider()
        if not token:
            raise NotifyError("未登录,无法发送紧急通知")
        return {"Authorization": f"Bearer {token}"}

    def send_emergency(self) -> dict:
        state = self.consent.get()
        if not state.emergency_authorized:
            raise NotifyError("未授权紧急联系人通知")
        if not state.channel or not state.contact:
            raise NotifyError("缺少紧急联系人信息")
        response = self._client.post(
            "/notify/emergency",
            headers=self._headers(),
            json={
                "channel": state.channel,
                "to": state.contact,
                "template_id": self.template_id,
                "params": {"nickname": self.nickname},
            },
        )
        if response.status_code != 200:
            raise NotifyError(f"通知发送失败: {response.status_code}")
        data = response.json()
        if data.get("status") != "sent":
            raise NotifyError("通知发送失败")
        return data

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
