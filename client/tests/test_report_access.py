"""按用户隔离会话与报告的测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client.app import create_app
from client.conversations import ConversationError
from client.profiles import RuntimeManager
from client.reports import ReportView, report_owner
from client.tests.support import FakeNotifier, make_config
from client.tests.test_reports import FakeReportGateway

LAN_ADDRESS = ("192.168.1.9", 5000)
DEVICE_HEADER = "X-Device-Token"

PENDING = [
    {"report_id": 1, "version": 1, "title": "小明-基因报告", "filename": "xiaoming.pdf"},
    {"report_id": 2, "version": 1, "title": "小红-基因报告", "filename": "xiaohong.pdf"},
    {"report_id": 3, "version": 1, "title": "基因检测报告（成年版）", "filename": "gene.pdf"},
]


def build_manager(tmp_path, *, lan=True):
    config = make_config(tmp_path / "data", lan=lan)
    return RuntimeManager(
        config,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )


def make_client(manager) -> TestClient:
    return TestClient(create_app(manager, "secret-token", dev_mode=True), client=LAN_ADDRESS)


def sync_main(manager) -> None:
    main = manager.main()
    main.gateway.pending = [dict(item) for item in PENDING]
    result = main.sync_reports()
    assert result["synced"] == len(PENDING)


def create_kid(manager, nickname, username):
    return manager.create_profile(nickname, username, "password1")


def test_report_owner_matching():
    profiles = [
        {"id": "main", "role": "main", "nickname": "我"},
        {"id": "p_a", "role": "sub", "nickname": "小明"},
        {"id": "p_b", "role": "sub", "nickname": "小明明"},
        {"id": "p_c", "role": "sub", "nickname": "红"},
    ]
    assert report_owner({"title": "小明-基因报告"}, profiles) == "p_a"
    assert report_owner({"filename": "小明明.pdf"}, profiles) == "p_b"
    assert report_owner({"title": "基因报告"}, profiles) == "main"
    # 多昵称命中取最长
    assert report_owner({"title": "小明明-报告"}, profiles) == "p_b"
    # 单字昵称不参与匹配
    assert report_owner({"title": "红红-报告"}, profiles) == "main"


def test_sub_profile_sees_only_own_reports(tmp_path):
    manager = build_manager(tmp_path)
    sync_main(manager)
    kid = create_kid(manager, "小明", "xiaoming")
    other = create_kid(manager, "小红", "xiaohong")

    assert len(manager.main().list_reports()["items"]) == 3

    kid_reports = manager.runtime_for(kid["id"]).list_reports()
    assert [item["title"] for item in kid_reports["items"]] == ["小明-基因报告"]
    assert kid_reports["unread"] == 1

    other_reports = manager.runtime_for(other["id"]).list_reports()
    assert [item["title"] for item in other_reports["items"]] == ["小红-基因报告"]
    assert other_reports["unread"] == 1

    manager.close()


def test_sub_profile_cannot_open_others_file(tmp_path):
    manager = build_manager(tmp_path)
    sync_main(manager)
    kid = create_kid(manager, "小明", "xiaoming")
    client = make_client(manager)
    token = client.post(
        "/api/device/login",
        json={"username": kid["username"], "password": "password1"},
    ).json()["device_token"]
    headers = {DEVICE_HEADER: token}

    listed = client.get("/api/reports", headers=headers).json()
    assert [item["report_id"] for item in listed["items"]] == [1]

    assert client.get("/api/reports/2/file", headers=headers).status_code == 404
    assert client.post("/api/reports/2/read", headers=headers).status_code == 404
    assert client.get("/api/reports/1/file", headers=headers).status_code == 200

    manager.close()


def test_sub_context_excludes_others_reports(tmp_path):
    manager = build_manager(tmp_path)
    sync_main(manager)
    kid = create_kid(manager, "小明", "xiaoming")
    view = ReportView(
        manager.main().reports,
        manager.profiles.raw(kid["id"]),
        manager.profiles.list,
    )

    own = view.context_text()
    assert "小明-基因报告" in own
    assert "小红-基因报告" not in own
    assert "基因检测报告（成年版）" not in own

    full = manager.main().reports.context_text()
    assert "小明-基因报告" in full
    assert "小红-基因报告" in full
    assert "基因检测报告（成年版）" in full

    manager.close()


def test_sub_sync_returns_only_own_items(tmp_path):
    manager = build_manager(tmp_path)
    sync_main(manager)
    kid = create_kid(manager, "小明", "xiaoming")
    create_kid(manager, "小红", "xiaohong")

    result = manager.runtime_for(kid["id"]).sync_reports()
    assert result["synced"] == 0
    assert [item["report_id"] for item in result["items"]] == [1]
    assert result["unread"] == 1

    manager.close()


def test_sessions_isolated_between_sub_profiles(tmp_path):
    manager = build_manager(tmp_path)
    kid = create_kid(manager, "小明", "xiaoming")
    other = create_kid(manager, "小红", "xiaohong")
    kid_runtime = manager.runtime_for(kid["id"])
    other_runtime = manager.runtime_for(other["id"])

    session = kid_runtime.create_session("小明自己的会话")

    assert [item["session_id"] for item in kid_runtime.list_sessions()["items"]] == [
        session["session_id"]
    ]
    # 每个档案各自只有一个会话，彼此不可见
    other_sessions = other_runtime.list_sessions()["items"]
    assert len(other_sessions) == 1
    assert other_sessions[0]["session_id"] != session["session_id"]
    main_sessions = manager.main().list_sessions()["items"]
    assert len(main_sessions) == 1
    assert main_sessions[0]["session_id"] != session["session_id"]
    with pytest.raises(ConversationError):
        other_runtime.get_session(session["session_id"])

    manager.close()
