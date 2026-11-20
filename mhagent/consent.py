"""同意书与紧急联系人授权状态的本地读写(加密)。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

CONSENT_KEY = "consent.state"
VALID_CHANNELS = {"sms", "email"}


@dataclass
class ConsentState:
    version: str | None = None
    emergency_authorized: bool = False
    channel: str | None = None
    contact: str | None = None
    authorized_at: str | None = None


class ConsentStore:
    def __init__(self, store):
        self.store = store

    def get(self) -> ConsentState:
        raw = self.store.kv_get(CONSENT_KEY) or {}
        return ConsentState(
            version=raw.get("version"),
            emergency_authorized=bool(raw.get("emergency_authorized", False)),
            channel=raw.get("channel"),
            contact=raw.get("contact"),
            authorized_at=raw.get("authorized_at"),
        )

    def save(self, state: ConsentState) -> ConsentState:
        if state.channel is not None and state.channel not in VALID_CHANNELS:
            raise ValueError("channel 必须是 sms 或 email")
        self.store.kv_set(CONSENT_KEY, asdict(state))
        return state

    def agree(self, version: str) -> ConsentState:
        if not version:
            raise ValueError("version 不能为空")
        state = self.get()
        state.version = version
        return self.save(state)

    def set_emergency_contact(self, channel: str, contact: str, *, authorized: bool = True) -> ConsentState:
        if channel not in VALID_CHANNELS:
            raise ValueError("channel 必须是 sms 或 email")
        if not isinstance(contact, str) or not contact.strip():
            raise ValueError("联系方式不能为空")
        state = self.get()
        state.channel = channel
        state.contact = contact.strip()
        state.emergency_authorized = bool(authorized)
        state.authorized_at = datetime.now(timezone.utc).isoformat() if authorized else None
        return self.save(state)

    def revoke_emergency(self) -> ConsentState:
        state = self.get()
        state.emergency_authorized = False
        state.authorized_at = None
        return self.save(state)
