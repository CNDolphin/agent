"""LLM 客户端抽象与错误类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol


class LLMError(Exception):
    """LLM 调用错误基类。"""


class InsufficientCredits(LLMError):
    """积分不足(402)。"""


class GatewayUnavailable(LLMError):
    """网关或上游不可用(502/超时/连接错误)。"""


class AuthExpired(LLMError):
    """登录失效,需要重新登录。"""


class DuplicateRequest(LLMError):
    """同一 X-Request-Id 已结算(409),由上层决定如何处理。"""

    def __init__(self, message: str = "重复请求", cost: int | None = None, balance: int | None = None):
        super().__init__(message)
        self.cost = cost
        self.balance = balance


@dataclass
class ChatResult:
    content: str
    input_hit: int = 0
    input_miss: int = 0
    output: int = 0
    cost: int = 0
    balance: int = 0
    low_balance: bool = False


class LLMClient(Protocol):
    def chat(self, messages: list[dict], *, max_tokens: int = 1024) -> ChatResult: ...

    def chat_stream(self, messages: list[dict], *, max_tokens: int = 1024) -> Iterator[str]: ...
