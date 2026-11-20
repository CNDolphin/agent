"""客户端测试的公共替身与配置构造。"""

from __future__ import annotations

import threading
import time

from mhagent.auth_session import TokenPair
from mhagent.llm.base import ChatResult

DEVICE_KEY = "test-device-key"


def make_config(data_dir, base_url: str = "http://127.0.0.1:9", *, lan: bool = False) -> dict:
    return {
        "gateway": {
            "base_url": base_url,
            "model": "deepseek-flash",
            "timeout_seconds": 5,
        },
        "storage": {"data_dir": str(data_dir)},
        "session": {"max_context_chars": 2000, "max_tokens": 1024},
        "client": {
            "dev_tools": True,
            "window": {"width": 1100, "height": 760},
            "lan": {"enabled": lan, "port": 8780},
        },
    }


class FakeGateway:
    """模拟 GatewayClient;记录调用并统计并发度。"""

    def __init__(self, session, *, is_new: bool = False, reply: str = "我在听。"):
        self.session = session
        self.base_url = "http://fake"
        self.is_new = is_new
        self.reply = reply
        self.sent_codes: list[str] = []
        self.agreed_versions: list[str] = []
        self.closed = False
        self.consent = {"version": "v1", "text": "测试同意书正文"}
        self.max_active = 0
        self._active = 0
        self._counter_lock = threading.Lock()

    # 认证
    def send_code(self, phone):
        self.sent_codes.append(phone)

    def login(self, phone, code):
        tokens = TokenPair("access-token", "refresh-token", 3600, self.is_new)
        self.session.save(tokens)
        return tokens

    def login_password(self, phone, password):
        if password != "correct-horse":
            from mhagent.llm.gateway import WrongPassword

            raise WrongPassword("手机号或密码错误")
        tokens = TokenPair("access-token", "refresh-token", 3600, self.is_new)
        self.session.save(tokens)
        return tokens

    def register(self, phone, code, password):
        tokens = TokenPair("access-token", "refresh-token", 3600, True)
        self.session.save(tokens)
        return tokens

    def reset_password(self, phone, code, new_password):
        return None

    def refresh(self):
        tokens = TokenPair("access-token-2", "refresh-token", 3600)
        self.session.save(tokens)
        return tokens

    # 同意书
    def get_latest_consent(self):
        return dict(self.consent)

    def agree_consent(self, version):
        self.agreed_versions.append(version)

    # 对话
    def chat(self, messages, *, max_tokens: int = 1024):
        with self._counter_lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(0.02)
        with self._counter_lock:
            self._active -= 1
        return ChatResult(content=self.reply)

    # 账户
    def get_balance(self):
        return {"balance": 120, "held": 0, "available": 120}

    def list_packages(self):
        return [{"id": 1, "name": "体验包", "price_cents": 990, "credits": 100}]

    def create_order(self, package_id, channel):
        return {"order_id": 7, "status": "pending", "pay_params": {"channel": channel}}

    def list_orders(self):
        return [{"id": 7, "status": "pending", "credits": 100}]

    def mock_pay(self, order_id, trade_no=None):
        return {"status": "paid", "order_id": int(order_id)}

    def close(self):
        self.closed = True


class FakeNotifier:
    def __init__(self):
        self.calls = 0

    def send_emergency(self):
        self.calls += 1
        return {"status": "sent"}

    def close(self):
        pass


def answer_all(runtime, value: int = 4) -> None:
    """把 80 题按同一倾向答完（正向 value，反向 6-value）。"""
    bank = runtime.onboarding.bank
    answers = {
        str(q["id"]): (6 - value if q["reverse"] else value) for q in bank.questions
    }
    runtime.save_onboarding_answers(answers)


def default_rankings(runtime) -> dict:
    bank = runtime.onboarding.bank
    return {
        "intel": list(bank.intel_ids),
        "ind": {
            item["id"]: [ind["id"] for ind in item["indicators"]]
            for item in bank.intelligences
        },
    }


def complete_onboarding(runtime, value: int = 4) -> dict:
    """题库答满 + 默认排序 + 完成测评。"""
    answer_all(runtime, value)
    runtime.save_onboarding_rankings(default_rankings(runtime))
    return runtime.complete_onboarding()
