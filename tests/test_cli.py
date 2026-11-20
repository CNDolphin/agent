from datetime import datetime, timedelta, timezone

import pytest

from mhagent.auth_session import AuthSession, TokenPair
from mhagent.cli_setup import CliSetup, SetupAborted
from mhagent.consent import ConsentStore
from mhagent.llm.gateway import CodeInvalid
from mhagent.store.crypto import DecryptError
from mhagent.store.db import LocalStore


class FakeAuth:
    def __init__(self, outcomes=None, is_new=False):
        self.outcomes = list(outcomes or [])
        self.is_new = is_new
        self.sent: list[str] = []
        self.logins: list[tuple[str, str]] = []

    def send_code(self, phone):
        self.sent.append(phone)

    def login(self, phone, code):
        self.logins.append((phone, code))
        item = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(item, Exception):
            raise item
        return TokenPair(access_token=f"access-{phone}", refresh_token="refresh", expires_in=3600, is_new=self.is_new)


class FakeConsent:
    def get_latest_consent(self):
        return {"version": "v2", "text": "同意书正文:对话内容会经网关发送给第三方模型服务。"}


def run_setup(tmp_path, inputs, **kwargs):
    output: list[str] = []

    def input_fn(prompt):
        if not inputs:
            raise AssertionError("输入用完了")
        return inputs.pop(0)

    setup = CliSetup(
        data_dir=tmp_path,
        input_fn=input_fn,
        output_fn=output.append,
        consent_client=FakeConsent(),
        **kwargs,
    )
    return setup.run(), output


def test_first_run_order(tmp_path):
    result, output = run_setup(
        tmp_path,
        ["pw", "13800000000", "123456", "y", "sms", "13900000000", "y"],
        auth=FakeAuth(is_new=True),
    )
    assert result.phone == "13800000000"
    assert result.is_new is True
    assert result.consent.version == "v2"
    assert result.consent.emergency_authorized is True
    assert result.consent.channel == "sms"
    assert any("首次使用需要设置本地口令" in line for line in output)
    assert any("第三方模型服务" in line for line in output)
    assert any("获赠 100 积分" in line for line in output)
    result.close()


def test_code_error_can_retry(tmp_path):
    auth = FakeAuth(outcomes=[CodeInvalid(), CodeInvalid(), None])
    result, output = run_setup(
        tmp_path,
        ["pw", "13800000000", "000000", "13800000000", "000000", "13800000000", "123456", "y", "跳过"],
        auth=auth,
    )
    assert len(auth.logins) == 3
    assert any("验证码错误" in line for line in output)
    assert result.consent.version == "v2"
    assert result.consent.emergency_authorized is False
    result.close()


def test_code_error_too_many_times(tmp_path):
    auth = FakeAuth(outcomes=[CodeInvalid(), CodeInvalid(), CodeInvalid()])
    with pytest.raises(SetupAborted) as exc:
        run_setup(
            tmp_path,
            ["pw", "138", "1", "138", "2", "138", "3"],
            auth=auth,
        )
    assert "稍后再试" in str(exc.value)


def test_reject_consent_saves_nothing(tmp_path):
    with pytest.raises(SetupAborted):
        run_setup(tmp_path, ["pw", "13800000000", "123456", "n"], auth=FakeAuth())
    store = LocalStore(tmp_path, "pw")
    assert store.record_count() == 0
    assert ConsentStore(store).get().version is None
    assert AuthSession(store).load() is None
    store.close()


def test_wrong_passphrase_keeps_data(tmp_path):
    store = LocalStore(tmp_path, "pw")
    store.add_record("journal", {"note": "PRIVATE-MARKER-xyz"})
    store.close()
    with pytest.raises(DecryptError):
        run_setup(tmp_path, ["wrong"], auth=FakeAuth())
    reopened = LocalStore(tmp_path, "pw")
    assert reopened.record_count() == 1
    reopened.close()


def test_token_expired_relogin_keeps_data(tmp_path):
    store = LocalStore(tmp_path, "pw")
    store.add_record("journal", {"note": "旧数据"})
    session = AuthSession(store)
    session.save(
        TokenPair(access_token="old", refresh_token="r", expires_in=1),
        saved_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    store.close()
    auth = FakeAuth()
    result, _ = run_setup(tmp_path, ["pw", "13800000000", "123456", "y", "跳过"], auth=auth)
    assert auth.logins
    assert result.store.record_count() == 1
    result.close()


def test_new_phone_prompts_about_original_account(tmp_path):
    store = LocalStore(tmp_path, "pw")
    store.add_record("journal", {"note": "原账号数据"})
    ConsentStore(store).agree("v2")
    store.kv_set("account.phone", "13800000000")
    store.close()
    with pytest.raises(SetupAborted):
        run_setup(tmp_path, ["pw", "13900000000", "123456", "n"], auth=FakeAuth())
    reopened = LocalStore(tmp_path, "pw")
    assert reopened.record_count() == 1
    assert reopened.kv_get("account.phone") == "13800000000"
    reopened.close()
