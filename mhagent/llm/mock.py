"""测试用的 mock LLM:按脚本返回内容或抛出指定异常,并记录收到的 messages。"""

from __future__ import annotations

from mhagent.llm.base import ChatResult
from mhagent.safety import Risk


class MockLLM:
    def __init__(self, script=None, *, default: str = "我在听,你可以慢慢说。", review_level: Risk = Risk.LOW):
        self.script = list(script or [])
        self.default = default
        self.review_level = review_level
        self.calls: list[list[dict]] = []
        self.stream_calls: list[list[dict]] = []
        self.review_calls = 0

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _next(self):
        item = self.script.pop(0) if self.script else self.default
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ChatResult):
            return item
        if isinstance(item, dict):
            return ChatResult(**item)
        return ChatResult(content=str(item))

    def chat(self, messages: list[dict], *, max_tokens: int = 1024) -> ChatResult:
        self.calls.append(list(messages))
        return self._next()

    def chat_stream(self, messages: list[dict], *, max_tokens: int = 1024):
        self.stream_calls.append(list(messages))
        result = self._next()
        text = result.content
        for i in range(0, len(text), 4):
            yield text[i:i + 4]

    def review_risk(self, text: str) -> Risk:
        self.review_calls += 1
        return self.review_level
