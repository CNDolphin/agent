"""Runtime 单元测试:设备密钥、密码登录、串行化、刷新重试、评估高危、会话。"""

from __future__ import annotations

import threading

import httpx
import pytest
import respx

from client.conversations import SessionLockedError
from client.onboarding import OnboardingRequired
from client.runtime import AccountMismatch, AlreadyOpened, NotOpened, Runtime
from client.tests.support import (
    DEVICE_KEY,
    FakeGateway,
    FakeNotifier,
    complete_onboarding,
    make_config,
)
from mhagent.auth_session import TokenPair
from mhagent.consent import ConsentStore
from mhagent.notifier import Notifier
from mhagent.store.crypto import DecryptError
from mhagent.store.db import LocalStore


def make_runtime(tmp_path, *, base_url="http://127.0.0.1:9", notifier=None):
    data_dir = tmp_path / "data"
    runtime = Runtime(
        make_config(data_dir, base_url),
        data_dir,
        device_key=DEVICE_KEY,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: notifier or FakeNotifier(),
    )
    runtime.open()
    return runtime


def test_wrong_device_key_keeps_data(tmp_path):
    data_dir = tmp_path / "data"
    store = LocalStore(data_dir, DEVICE_KEY)
    store.add_record("session", {"marker": "keep"})
    store.close()

    runtime = Runtime(make_config(data_dir), data_dir, device_key="another-key")
    with pytest.raises(DecryptError):
        runtime.open()
    assert runtime.opened is False
    assert (data_dir / "meta.json").exists()

    runtime = Runtime(make_config(data_dir), data_dir, device_key=DEVICE_KEY)
    runtime.open()
    assert runtime.store.list_records("session")[0]["payload"] == {"marker": "keep"}
    runtime.close()
    assert runtime.opened is False


def test_open_twice_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    with pytest.raises(AlreadyOpened):
        runtime.open()
    runtime.close()


def test_password_login_and_phone_mask(tmp_path):
    runtime = make_runtime(tmp_path)
    gateway = runtime.gateway
    gateway.is_new = True

    runtime.send_code("13800138000")
    assert gateway.sent_codes == ["13800138000"]

    result = runtime.login_password("13800138000", "correct-horse")
    assert result == {"is_new": True, "phone_mask": "138****8000"}
    assert runtime.store.kv_get("account.phone") == "13800138000"
    assert runtime.status()["logged_in"] is True


def test_password_login_other_phone_requires_confirmation(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.store.kv_set("account.phone", "13800138000")

    with pytest.raises(AccountMismatch) as exc_info:
        runtime.login_password("13900139000", "correct-horse")
    assert exc_info.value.previous_phone_mask == "138****8000"
    # 被拒绝时撤销刚拿到的令牌,原账号绑定保持不变
    assert runtime.session.load() is None
    assert runtime.store.kv_get("account.phone") == "13800138000"

    result = runtime.login_password("13900139000", "correct-horse", force=True)
    assert result["phone_mask"] == "139****9000"
    assert runtime.store.kv_get("account.phone") == "13900139000"


def test_register_sets_phone(tmp_path):
    runtime = make_runtime(tmp_path)
    result = runtime.register("13800138000", "123456", "correct-horse")
    assert result["is_new"] is True
    assert runtime.store.kv_get("account.phone") == "13800138000"


def test_sub_profile_cannot_login(tmp_path):
    data_dir = tmp_path / "sub"
    runtime = Runtime(
        make_config(data_dir),
        data_dir,
        profile={"id": "p_1", "role": "sub", "nickname": "孩子"},
        device_key=DEVICE_KEY,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    runtime.open()
    with pytest.raises(ValueError):
        runtime.login_password("13800138000", "correct-horse")
    with pytest.raises(ValueError):
        runtime.send_code("13800138000")
    runtime.close()


def test_chat_calls_are_serialized(tmp_path):
    runtime = make_runtime(tmp_path)
    complete_onboarding(runtime)
    gateway = runtime.gateway
    replies: list[str] = []

    def worker():
        replies.append(runtime.chat("你好")["reply"])

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(replies) == 5
    assert gateway.max_active == 1
    assert replies[0] == "我在听。"


def test_chat_requires_onboarding(tmp_path):
    runtime = make_runtime(tmp_path)
    with pytest.raises(OnboardingRequired):
        runtime.chat("你好")


def test_chat_creates_session_and_returns_id(tmp_path):
    runtime = make_runtime(tmp_path)
    complete_onboarding(runtime)
    result = runtime.chat("你好")
    session_id = result["session_id"]
    assert session_id.startswith("s_")

    detail = runtime.get_session(session_id)
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]
    assert detail["title"] == "我的会话"
    assert runtime.list_sessions()["items"][0]["message_count"] == 2


def test_chat_can_continue_existing_session(tmp_path):
    runtime = make_runtime(tmp_path)
    complete_onboarding(runtime)
    first = runtime.chat("第一句")["session_id"]
    runtime.chat("第二句", session_id=first)
    detail = runtime.get_session(first)
    assert len(detail["messages"]) == 4
    assert len(runtime.list_sessions()["items"]) == 1


def test_chat_reuses_single_session(tmp_path):
    runtime = make_runtime(tmp_path)
    complete_onboarding(runtime)
    first = runtime.chat("第一句")["session_id"]
    second = runtime.chat("另一段对话")["session_id"]
    assert first == second
    assert runtime.loop._history[0]["content"] == "第一句"


def test_session_crud(tmp_path):
    runtime = make_runtime(tmp_path)
    created = runtime.create_session("手动创建")
    assert created["title"] == "我的会话"
    renamed = runtime.rename_session(created["session_id"], "改了名字")
    assert renamed["title"] == "改了名字"
    with pytest.raises(SessionLockedError):
        runtime.delete_session(created["session_id"])
    assert runtime.get_session(created["session_id"])["title"] == "改了名字"


def test_not_opened_rejects_calls(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.close()
    with pytest.raises(NotOpened):
        runtime.chat("你好")
    with pytest.raises(NotOpened):
        runtime.balance()


def test_account_request_refreshes_token_once(tmp_path):
    runtime = Runtime(
        make_config(tmp_path / "data", "http://gw"),
        tmp_path / "data",
        device_key=DEVICE_KEY,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    runtime.open()
    runtime.session.save(TokenPair("old-token", "refresh-token", 60))

    with respx.mock(base_url="http://gw") as router:
        router.get("/credits/balance").mock(
            side_effect=[
                httpx.Response(401),
                httpx.Response(
                    200, json={"balance": 80, "held": 0, "available": 80}
                ),
            ]
        )
        refresh = router.post("/auth/refresh").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
            )
        )
        result = runtime.balance()

    assert result == {"balance": 80, "held": 0, "available": 80}
    assert refresh.called
    assert runtime.session.load().access_token == "new-token"


def test_high_risk_assessment_notifies_contact(tmp_path):
    notifier = FakeNotifier()
    runtime = make_runtime(tmp_path, notifier=notifier)
    runtime.set_contact("sms", "13900001111", authorized=True)

    outcome = runtime.evaluate("phq9", [0, 0, 0, 0, 0, 0, 0, 0, 3])

    assert outcome["high_risk"] is True
    assert outcome["notified"] is True
    assert outcome["state"] == "CRISIS"
    assert notifier.calls == 1
    assert len(runtime.store.list_records("assessment")) == 1


def test_notifier_sends_authorization_header(tmp_path):
    store = LocalStore(tmp_path / "notify", "pw")
    consent = ConsentStore(store)
    consent.set_emergency_contact("sms", "13900001111", authorized=True)
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"status": "sent", "notify_id": "n1"})

    client = httpx.Client(base_url="http://gw", transport=httpx.MockTransport(handler))
    notifier = Notifier(
        "http://gw",
        consent,
        http_client=client,
        token_provider=lambda: "token-1",
    )
    try:
        assert notifier.send_emergency()["status"] == "sent"
        assert seen["auth"] == "Bearer token-1"
    finally:
        client.close()
        store.close()


def test_dev_sms_code_proxies_backend(tmp_path):
    runtime = Runtime(
        make_config(tmp_path / "data", "http://gw"),
        tmp_path / "data",
        device_key=DEVICE_KEY,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    runtime.open()

    with respx.mock(base_url="http://gw") as router:
        route = router.get("/dev/sms/last").mock(
            return_value=httpx.Response(200, json={"code": "123456"})
        )
        code = runtime.dev_sms_code("13800138000")

    assert code == "123456"
    assert route.called
    assert route.calls[0].request.url.params["phone"] == "13800138000"
