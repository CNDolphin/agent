"""登录令牌的加密持久化。

令牌只保存在本地加密库(kv)中,不写明文文件,也不写日志。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

TOKEN_KEY = "auth.tokens"
TIME_KEY = "auth.tokens.saved_at"
EXPIRY_MARGIN_SECONDS = 60


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str = ""
    expires_in: int = 3600
    is_new: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthSession:
    def __init__(self, store=None):
        self._store = store
        self._memory: dict | None = None

    def save(self, tokens: TokenPair, *, saved_at=None) -> TokenPair:
        saved = (saved_at or _now()).astimezone(timezone.utc).isoformat()
        data = {"tokens": asdict(tokens), "saved_at": saved}
        if self._store is not None:
            self._store.kv_set(TOKEN_KEY, data)
            self._store.kv_set(TIME_KEY, saved)
        else:
            self._memory = data
        return tokens

    def load(self) -> TokenPair | None:
        if self._store is not None:
            data = self._store.kv_get(TOKEN_KEY)
            if not data:
                return None
        else:
            data = self._memory
        if not data:
            return None
        tokens = data.get("tokens", {})
        return TokenPair(
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
            expires_in=int(tokens.get("expires_in", 0)),
            is_new=bool(tokens.get("is_new", False)),
        )

    def saved_at(self) -> datetime | None:
        if self._store is not None:
            raw = self._store.kv_get(TIME_KEY)
        else:
            raw = (self._memory or {}).get("saved_at")
        if not raw:
            return None
        return datetime.fromisoformat(raw)

    def valid(self, now=None) -> bool:
        tokens = self.load()
        if not tokens or not tokens.access_token:
            return False
        saved = self.saved_at()
        if saved is None:
            return False
        current = (now or _now()).astimezone(timezone.utc)
        expires_at = saved + timedelta(seconds=tokens.expires_in - EXPIRY_MARGIN_SECONDS)
        return current < expires_at

    def clear(self) -> None:
        self._memory = None
        if self._store is not None:
            self._store.kv_delete(TOKEN_KEY)
            self._store.kv_delete(TIME_KEY)
