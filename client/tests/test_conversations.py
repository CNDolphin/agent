"""会话存储测试:唯一会话、追加、重命名与隔离。"""

from __future__ import annotations

import pytest

from client.conversations import (
    DEFAULT_TITLE,
    ConversationError,
    ConversationStore,
    SessionLockedError,
)
from mhagent.store.db import LocalStore


def _store(tmp_path):
    return LocalStore(tmp_path, "device-key")


def test_create_and_get_empty_session(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    session = conversations.create()
    assert session["session_id"].startswith("s_")
    assert session["title"] == DEFAULT_TITLE
    data = conversations.get(session["session_id"])
    assert data["messages"] == []
    store.close()


def test_append_keeps_default_title_and_updates_time(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    session = conversations.create()
    conversations.append(session["session_id"], "user", "今天心情有点低落")
    conversations.append(session["session_id"], "assistant", "我在听,慢慢说。")

    data = conversations.get(session["session_id"])
    assert [item["role"] for item in data["messages"]] == ["user", "assistant"]
    assert data["title"] == DEFAULT_TITLE
    assert data["updated_at"] >= data["created_at"]

    listed = conversations.list_sessions()
    assert listed[0]["message_count"] == 2
    assert listed[0]["preview"] == "今天心情有点低落"
    store.close()


def test_append_rejects_bad_role(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    session = conversations.create()
    with pytest.raises(ConversationError):
        conversations.append(session["session_id"], "system", "x")
    store.close()


def test_missing_session_raises(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    with pytest.raises(ConversationError):
        conversations.get("s_missing")
    with pytest.raises(ConversationError):
        conversations.append("s_missing", "user", "x")
    store.close()


def test_rename_session(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    session = conversations.create()
    result = conversations.rename(session["session_id"], "  新的标题  ")
    assert result["title"] == "新的标题"
    with pytest.raises(ConversationError):
        conversations.rename(session["session_id"], "   ")
    store.close()


def test_delete_session_is_forbidden(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    session = conversations.create()
    conversations.append(session["session_id"], "user", "你好")
    with pytest.raises(SessionLockedError):
        conversations.delete(session["session_id"])
    assert len(conversations.list_sessions()) == 1
    assert len(store.list_records("chat_message")) == 1
    store.close()


def test_ensure_primary_returns_earliest_session(tmp_path):
    store = _store(tmp_path)
    conversations = ConversationStore(store)
    assert conversations.list_sessions() == []
    primary = conversations.ensure_primary()
    assert primary["title"] == DEFAULT_TITLE
    second = conversations.create("历史会话")
    listed = conversations.list_sessions()
    assert [item["session_id"] for item in listed] == [primary["session_id"]]
    assert conversations.ensure_primary()["session_id"] == primary["session_id"]
    # 历史会话不再可访问
    with pytest.raises(ConversationError):
        conversations.get(second["session_id"])
    store.close()


def test_sessions_are_isolated_per_store(tmp_path):
    main = _store(tmp_path / "main")
    sub = _store(tmp_path / "sub")
    conversations = ConversationStore(main)
    session = conversations.create()
    assert ConversationStore(sub).list_sessions() == []
    assert len(conversations.list_sessions()) == 1
    main.close()
    sub.close()
