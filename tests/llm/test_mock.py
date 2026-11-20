import pytest

from mhagent.llm.base import ChatResult, InsufficientCredits
from mhagent.llm.mock import MockLLM
from mhagent.safety import Risk


def test_scripted_responses_and_messages():
    llm = MockLLM(["第一次回复", ChatResult(content="第二次", cost=2)])
    first = llm.chat([{"role": "user", "content": "你好"}])
    assert first.content == "第一次回复"
    second = llm.chat([{"role": "user", "content": "再见"}])
    assert second.content == "第二次"
    assert second.cost == 2
    assert llm.call_count == 2
    assert llm.calls[0][0]["content"] == "你好"
    assert llm.calls[1][0]["content"] == "再见"


def test_scripted_exception():
    llm = MockLLM([InsufficientCredits("no credits"), "兜底"])
    with pytest.raises(InsufficientCredits):
        llm.chat([{"role": "user", "content": "hi"}])
    assert llm.chat([{"role": "user", "content": "hi"}]).content == "兜底"


def test_stream_and_default():
    llm = MockLLM(default="默认回复")
    chunks = list(llm.chat_stream([{"role": "user", "content": "hi"}]))
    assert "".join(chunks) == "默认回复"
    assert llm.stream_calls


def test_review_risk():
    llm = MockLLM(review_level=Risk.MEDIUM)
    assert llm.review_risk("随便说点什么") == Risk.MEDIUM
    assert llm.review_calls == 1
