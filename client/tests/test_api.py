"""本地 API 测试:来源分流鉴权、密码登录、档案/会话、开发接口开关。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client.app import create_app
from client.profiles import RuntimeManager
from client.tests.support import (
    FakeGateway,
    FakeNotifier,
    complete_onboarding,
    make_config,
)

TOKEN_HEADER = {"X-Local-Token": "secret-token"}
LAN_ADDRESS = ("192.168.1.9", 5000)


def finish_onboarding(manager):
    """替当前激活档案完成测评，便于后续调用 /api/chat。"""
    complete_onboarding(manager.runtime_for())


def build(tmp_path, *, dev_mode=True, lan=False):
    config = make_config(tmp_path / "data", lan=lan)
    manager = RuntimeManager(
        config,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=dev_mode)
    return TestClient(app), manager


def lan_client(tmp_path, *, dev_mode=True):
    config = make_config(tmp_path / "data", lan=True)
    manager = RuntimeManager(
        config,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=dev_mode)
    return TestClient(app, client=LAN_ADDRESS), manager


def test_requires_local_token(tmp_path):
    client, manager = build(tmp_path)
    response = client.get("/api/sessions")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"

    response = client.get("/api/sessions", headers={"X-Local-Token": "wrong"})
    assert response.status_code == 401
    # 公开路径(健康检查与状态)不需要令牌
    assert client.get("/api/health").status_code == 200
    manager.close()


def test_desktop_status_without_login(tmp_path):
    client, manager = build(tmp_path)
    status = client.get("/api/status", headers=TOKEN_HEADER).json()
    assert status["device_mode"] == "desktop"
    assert status["legacy_required"] is False
    assert status["logged_in"] is False
    assert [item["id"] for item in status["profiles"]] == ["main"]
    assert status["dev_mode"] is True
    manager.close()


def test_password_login_flow_and_account_mismatch(tmp_path):
    client, manager = build(tmp_path)
    manager.main().gateway.is_new = True

    response = client.post(
        "/api/auth/send-code", headers=TOKEN_HEADER, json={"phone": "13800138000"}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    response = client.post(
        "/api/auth/login",
        headers=TOKEN_HEADER,
        json={"phone": "13800138000", "password": "correct-horse"},
    )
    assert response.status_code == 200
    assert response.json() == {"is_new": True, "phone_mask": "138****8000"}

    response = client.post(
        "/api/auth/login",
        headers=TOKEN_HEADER,
        json={"phone": "13900139000", "password": "correct-horse"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "account_mismatch"
    assert body["previous_phone_mask"] == "138****8000"

    manager.close()


def test_wrong_password_maps_to_401(tmp_path):
    client, manager = build(tmp_path)
    response = client.post(
        "/api/auth/login",
        headers=TOKEN_HEADER,
        json={"phone": "13800138000", "password": "nope"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "wrong_password"
    manager.close()


def test_register_and_reset_password(tmp_path):
    client, manager = build(tmp_path)
    response = client.post(
        "/api/auth/register",
        headers=TOKEN_HEADER,
        json={"phone": "13800138000", "code": "123456", "password": "correct-horse"},
    )
    assert response.status_code == 200
    assert response.json()["is_new"] is True

    response = client.post(
        "/api/auth/reset-password",
        headers=TOKEN_HEADER,
        json={"phone": "13800138000", "code": "123456", "new_password": "another-pass"},
    )
    assert response.status_code == 200
    manager.close()


def test_auth_routes_reject_lan(tmp_path):
    client, manager = lan_client(tmp_path)
    manager.create_profile("孩子", "kid_01", "password-1")
    token = client.post(
        "/api/device/login", json={"username": "kid_01", "password": "password-1"}
    ).json()["device_token"]
    response = client.post(
        "/api/auth/login",
        headers={"X-Device-Token": token},
        json={"phone": "13800138000", "password": "correct-horse"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "desktop_only"
    manager.close()


def test_profile_crud_desktop_only(tmp_path):
    client, manager = build(tmp_path)
    created = client.post(
        "/api/profiles",
        headers=TOKEN_HEADER,
        json={"nickname": "孩子", "username": "kid_01", "password": "password-1"},
    ).json()
    assert created["role"] == "sub"

    items = client.get("/api/profiles", headers=TOKEN_HEADER).json()["items"]
    assert {item["id"] for item in items} == {"main", created["id"]}

    updated = client.patch(
        f"/api/profiles/{created['id']}",
        headers=TOKEN_HEADER,
        json={"nickname": "小明", "note": "备用账号"},
    ).json()
    assert updated["nickname"] == "小明"

    assert manager.status()["active_profile"]["id"] == "main"
    activated = client.post(
        f"/api/profiles/{created['id']}/activate", headers=TOKEN_HEADER
    ).json()
    assert activated["active_profile"]["id"] == created["id"]

    assert client.delete(
        "/api/profiles/main", headers=TOKEN_HEADER
    ).status_code == 409
    assert client.delete(
        f"/api/profiles/{created['id']}", headers=TOKEN_HEADER
    ).json() == {"ok": True}
    manager.close()


def test_lan_cannot_manage_profiles(tmp_path):
    client, manager = lan_client(tmp_path)
    response = client.get("/api/profiles")
    assert response.status_code == 401
    assert response.json()["code"] == "device_auth_required"
    manager.close()


def test_device_login_and_sessions(tmp_path):
    client, manager = lan_client(tmp_path)
    manager.create_profile("孩子", "kid_01", "password-1")

    response = client.post(
        "/api/device/login", json={"username": "kid_01", "password": "password-1"}
    )
    assert response.status_code == 200
    token = response.json()["device_token"]
    header = {"X-Device-Token": token}

    status = client.get("/api/status", headers=header).json()
    assert status["device_mode"] == "lan"
    assert status["logged_in"] is True
    assert status["active_profile"]["username"] == "kid_01"
    assert status["profiles"] == []

    sessions = client.get("/api/sessions", headers=header).json()
    assert len(sessions["items"]) == 1
    created = client.post("/api/sessions", headers=header, json={"title": "手机端"}).json()
    assert created["session_id"] == sessions["items"][0]["session_id"]

    # 子账号之间、子账号与主账号的会话彼此隔离
    main_sessions = manager.runtime_for("main").list_sessions()
    assert main_sessions["items"][0]["session_id"] != created["session_id"]
    manager.close()


def test_device_login_rejects_bad_credentials(tmp_path):
    client, manager = lan_client(tmp_path)
    manager.create_profile("孩子", "kid_01", "password-1")
    response = client.post(
        "/api/device/login", json={"username": "kid_01", "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "device_auth_required"
    manager.close()


def test_lan_status_without_token(tmp_path):
    client, manager = lan_client(tmp_path)
    status = client.get("/api/status").json()
    assert status["device_mode"] == "lan"
    assert status["logged_in"] is False
    manager.close()


def test_session_crud(tmp_path):
    client, manager = build(tmp_path)
    finish_onboarding(manager)
    response = client.post(
        "/api/chat", headers=TOKEN_HEADER, json={"text": "我想自杀"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["crisis"] is True
    assert body["state"] == "CRISIS"
    assert "12356" in body["reply"]
    session_id = body["session_id"]

    detail = client.get(f"/api/sessions/{session_id}", headers=TOKEN_HEADER).json()
    assert len(detail["messages"]) == 2

    renamed = client.patch(
        f"/api/sessions/{session_id}", headers=TOKEN_HEADER, json={"title": "危机对话"}
    ).json()
    assert renamed["title"] == "危机对话"

    deleted = client.delete(f"/api/sessions/{session_id}", headers=TOKEN_HEADER)
    assert deleted.status_code == 400
    assert deleted.json()["code"] == "session_locked"
    assert client.get(f"/api/sessions/{session_id}", headers=TOKEN_HEADER).status_code == 200
    manager.close()


def test_chat_uses_given_session(tmp_path):
    client, manager = build(tmp_path)
    finish_onboarding(manager)
    session = client.post(
        "/api/sessions", headers=TOKEN_HEADER, json={"title": "固定会话"}
    ).json()
    response = client.post(
        "/api/chat",
        headers=TOKEN_HEADER,
        json={"text": "你好", "session_id": session["session_id"]},
    ).json()
    assert response["session_id"] == session["session_id"]
    assert len(client.get("/api/sessions", headers=TOKEN_HEADER).json()["items"]) == 1
    manager.close()


def test_balance_and_scales(tmp_path):
    client, manager = build(tmp_path)
    credits = client.get("/api/credits", headers=TOKEN_HEADER).json()
    assert credits["balance"] == 120

    scales = client.get("/api/scales", headers=TOKEN_HEADER).json()["items"]
    assert [item["id"] for item in scales] == ["phq9", "gad7", "pss10"]
    assert next(item for item in scales if item["id"] == "pss10")["available"] is False

    detail = client.get("/api/scales/phq9", headers=TOKEN_HEADER).json()
    assert len(detail["items"]) == 9

    response = client.post(
        "/api/scales/phq9/submit",
        headers=TOKEN_HEADER,
        json={"answers": [0, 0, 0, 0, 0, 0, 0, 0, 3]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["high_risk"] is True
    assert body["state"] == "CRISIS"

    response = client.post(
        "/api/scales/pss10/submit",
        headers=TOKEN_HEADER,
        json={"answers": [0] * 10},
    )
    assert response.status_code == 400
    manager.close()


def test_consent_and_contact(tmp_path):
    client, manager = build(tmp_path)
    consent = client.get("/api/consents/latest", headers=TOKEN_HEADER).json()
    assert consent["latest"]["version"] == "v1"

    response = client.post(
        "/api/consents/agree", headers=TOKEN_HEADER, json={"version": "v1"}
    )
    assert response.status_code == 200
    assert response.json()["consent"]["version"] == "v1"

    response = client.post(
        "/api/contact",
        headers=TOKEN_HEADER,
        json={"channel": "sms", "value": "13900001111", "authorized": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["emergency_authorized"] is True
    assert body["contact"] == "13900001111"

    response = client.delete("/api/contact", headers=TOKEN_HEADER)
    assert response.json()["emergency_authorized"] is False
    manager.close()


def test_dev_routes_disabled(tmp_path):
    client, manager = build(tmp_path, dev_mode=False)
    for path in ("/api/dev-token", "/api/dev/sms-code?phone=13800138000"):
        response = client.get(path, headers=TOKEN_HEADER)
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    response = client.post("/api/orders/7/mock-pay", headers=TOKEN_HEADER)
    assert response.status_code == 404
    manager.close()


def test_dev_token_and_sms_code_loopback_only(tmp_path, monkeypatch):
    client, manager = build(tmp_path, dev_mode=True)
    token = client.get("/api/dev-token")
    assert token.status_code == 200
    assert token.json()["token"] == "secret-token"

    monkeypatch.setattr(manager, "dev_sms_code", lambda phone: "123456")
    response = client.get("/api/dev/sms-code?phone=13800138000", headers=TOKEN_HEADER)
    assert response.json() == {"code": "123456"}

    lan, lan_manager = lan_client(tmp_path / "lan", dev_mode=True)
    assert lan.get("/api/dev-token").status_code == 403
    assert (
        lan.get("/api/dev/sms-code?phone=13800138000").status_code
        == 401
    )
    manager.close()
    lan_manager.close()


def test_orders_and_mock_pay(tmp_path):
    client, manager = build(tmp_path, dev_mode=True)
    packages = client.get("/api/packages", headers=TOKEN_HEADER).json()["items"]
    assert packages[0]["id"] == 1

    response = client.post(
        "/api/orders", headers=TOKEN_HEADER, json={"package_id": 1, "channel": "mock"}
    )
    assert response.status_code == 200
    assert response.json()["order_id"] == 7

    response = client.post(
        "/api/orders", headers=TOKEN_HEADER, json={"package_id": 1, "channel": "alipay"}
    )
    assert response.status_code == 400

    paid = client.post("/api/orders/7/mock-pay", headers=TOKEN_HEADER).json()
    assert paid["status"] == "paid"

    orders = client.get("/api/orders", headers=TOKEN_HEADER).json()["items"]
    assert orders[0]["id"] == 7
    manager.close()


def test_practices_endpoints(tmp_path):
    client, manager = build(tmp_path)
    items = client.get("/api/practices", headers=TOKEN_HEADER).json()["items"]
    assert "breathing_478" in [item["id"] for item in items]

    detail = client.get("/api/practices/breathing_478", headers=TOKEN_HEADER).json()
    assert detail["name"] == "4-7-8 呼吸"
    assert len(detail["steps"]) == 3

    response = client.get("/api/practices/not-exist", headers=TOKEN_HEADER)
    assert response.status_code == 404
    manager.close()


def test_crisis_endpoint(tmp_path):
    client, manager = build(tmp_path)
    body = client.get("/api/crisis", headers=TOKEN_HEADER).json()
    assert {item["number"] for item in body["hotlines"]} == {"12356", "120"}
    assert "12356" in body["copy_text"]
    manager.close()


def test_legacy_migrate_route(tmp_path):
    from mhagent.store.db import LocalStore

    data_dir = tmp_path / "data"
    store = LocalStore(data_dir, "old-pass")
    store.add_record("journal", {"note": "旧数据"})
    store.close()

    manager = RuntimeManager(
        make_config(data_dir),
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=True)
    client = TestClient(app)

    status = client.get("/api/status", headers=TOKEN_HEADER).json()
    assert status["legacy_required"] is True

    response = client.post(
        "/api/legacy/migrate", headers=TOKEN_HEADER, json={"passphrase": "wrong"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_passphrase"

    response = client.post(
        "/api/legacy/migrate", headers=TOKEN_HEADER, json={"passphrase": "old-pass"}
    )
    assert response.status_code == 200
    assert response.json()["legacy_required"] is False
    assert manager.runtime_for().store.list_records("journal")[0]["payload"]["note"] == "旧数据"
    manager.close()
