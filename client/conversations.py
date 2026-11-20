"""本地会话存储:会话元数据与会话消息都写在加密的 LocalStore.records 里。

- kind=`chat_session`,payload=`{session_id, title, created_at, updated_at}`
- kind=`chat_message`,payload=`{session_id, role, text, created_at}`

会话按档案目录天然隔离,不上传云端。
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

SESSION_KIND = "chat_session"
MESSAGE_KIND = "chat_message"
DEFAULT_TITLE = "我的会话"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationError(Exception):
    """会话不存在或参数错误。"""


class SessionLockedError(ConversationError):
    """唯一会话不可删除。"""


class ConversationStore:
    def __init__(self, store, clock=None):
        self.store = store
        self._clock = clock

    def now(self) -> datetime:
        current = self._clock() if self._clock else _now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    # ---- 会话 ----
    def create(self, title: str = "") -> dict:
        session_id = f"s_{secrets.token_hex(8)}"
        now = self.now().isoformat()
        payload = {
            "session_id": session_id,
            "title": str(title or DEFAULT_TITLE),
            "created_at": now,
            "updated_at": now,
        }
        record_id = self.store.add_record(SESSION_KIND, payload, created_at=now)
        return {"id": record_id, **payload, "message_count": 0, "preview": ""}

    def _primary_record(self) -> dict | None:
        """主会话 = 最早创建的一条；历史多会话只保留它。"""
        records = self.store.list_records(SESSION_KIND)
        if not records:
            return None
        records.sort(key=lambda item: (str(item["payload"].get("created_at") or ""), item["id"]))
        return records[0]

    def ensure_primary(self) -> dict:
        """返回唯一会话，不存在则创建。"""
        record = self._primary_record()
        if record is None:
            return self.create(DEFAULT_TITLE)
        payload = record["payload"]
        counter = self._counter(str(payload.get("session_id")))
        return {
            "id": record["id"],
            "session_id": payload.get("session_id"),
            "title": payload.get("title") or DEFAULT_TITLE,
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "message_count": counter["count"],
            "preview": counter["preview"],
        }

    def _counter(self, session_id: str) -> dict:
        item = {"count": 0, "preview": ""}
        for record in self.store.list_records(MESSAGE_KIND):
            payload = record["payload"]
            if str(payload.get("session_id")) != session_id:
                continue
            item["count"] += 1
            if payload.get("role") == "user" and payload.get("text") and not item["preview"]:
                item["preview"] = str(payload["text"])[:40]
        return item

    def list_sessions(self) -> list[dict]:
        """只返回唯一会话。"""
        record = self._primary_record()
        if record is None:
            return []
        payload = record["payload"]
        counter = self._counter(str(payload.get("session_id")))
        return [
            {
                "id": record["id"],
                "session_id": payload.get("session_id"),
                "title": payload.get("title") or DEFAULT_TITLE,
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
                "message_count": counter["count"],
                "preview": counter["preview"],
            }
        ]

    def _find(self, session_id: str) -> tuple[int, dict]:
        record = self._primary_record()
        if record is None or record["payload"].get("session_id") != session_id:
            raise ConversationError("会话不存在")
        return record["id"], dict(record["payload"])

    def get(self, session_id: str) -> dict:
        _, payload = self._find(session_id)
        messages = []
        for record in self.store.list_records(MESSAGE_KIND):
            item = record["payload"]
            if item.get("session_id") != session_id:
                continue
            messages.append(
                {
                    "id": record["id"],
                    "role": item.get("role"),
                    "text": item.get("text") or "",
                    "created_at": item.get("created_at"),
                }
            )
        return {
            "id": payload.get("session_id"),
            "session_id": session_id,
            "title": payload.get("title") or DEFAULT_TITLE,
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "messages": messages,
        }

    def append(self, session_id: str, role: str, text: str) -> None:
        if role not in ("user", "assistant"):
            raise ConversationError("消息角色只能是 user 或 assistant")
        record_id, payload = self._find(session_id)
        now_dt = self.now()
        now_text = now_dt.isoformat()
        self.store.add_record(
            MESSAGE_KIND,
            {
                "session_id": session_id,
                "role": role,
                "text": str(text or ""),
                "created_at": now_text,
            },
            created_at=now_dt,
        )
        payload["updated_at"] = now_text
        self.store.update_record(record_id, payload)

    def rename(self, session_id: str, title: str) -> dict:
        name = "" if title is None else str(title).strip()
        if not name:
            raise ConversationError("会话标题不能为空")
        record_id, payload = self._find(session_id)
        payload["title"] = name[:60]
        payload["updated_at"] = self.now().isoformat()
        self.store.update_record(record_id, payload)
        return {"session_id": session_id, "title": payload["title"]}

    def delete(self, session_id: str) -> None:
        raise SessionLockedError("会话不可删除")
