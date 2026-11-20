import json
from datetime import datetime, timezone

import pytest

from mhagent.consent import ConsentStore
from mhagent.llm.base import ChatResult, GatewayUnavailable, InsufficientCredits
from mhagent.llm.mock import MockLLM
from mhagent.loop import AgentLoop, State
from mhagent.safety import Risk
from mhagent.store.db import LocalStore

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
MARKER = "PRIVATE-MARKER-xyz"
CONTACT = "13900001111"


class FakeNotifier:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def send_emergency(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("network down")
        return {"status": "sent"}


@pytest.fixture
def make_loop(tmp_path):
    stores: list[LocalStore] = []
    counter = {"n": 0}

    def _make(script=None, *, authorized=False, notifier=None, review_level=Risk.LOW):
        counter["n"] += 1
        store = LocalStore(tmp_path / f"d{counter['n']}", "pw")
        stores.append(store)
        consent = ConsentStore(store)
        if authorized:
            consent.set_emergency_contact("sms", CONTACT, authorized=True)
        llm = MockLLM(script, review_level=review_level)
        loop = AgentLoop(llm, store, consent=consent, notifier=notifier, clock=lambda: NOW)
        return loop, llm, store, consent

    yield _make
    for store in stores:
        store.close()


def test_normal_chat_calls_llm(make_loop):
    loop, llm, store, _ = make_loop(["我听到你了。"])
    reply = loop.handle("最近有点累")
    assert reply == "我听到你了。"
    assert llm.call_count == 1
    assert llm.calls[0][-1] == {"role": "user", "content": "最近有点累"}
    assert store.list_records("session")[-1]["payload"]["user"] == "最近有点累"


def test_high_risk_skips_gateway(make_loop):
    loop, llm, store, _ = make_loop(["不应该被调用"])
    reply = loop.handle("我想死")
    assert "12356" in reply and "120" in reply
    assert llm.call_count == 0
    assert loop.state == State.CRISIS


def test_crisis_state_does_not_start_assessment(make_loop):
    loop, llm, store, _ = make_loop(["我在这里陪你。"])
    loop.handle("我想自杀")
    reply = loop.handle("我想做个焦虑测试")
    assert loop.state == State.CRISIS
    assert "第 1/" not in reply
    assert "题:" not in reply


def test_authorized_notifier_called_once(make_loop):
    notifier = FakeNotifier()
    loop, llm, store, consent = make_loop(["不应该被调用"], authorized=True, notifier=notifier)
    first = loop.handle("我想死")
    assert notifier.calls == 1
    assert "将通知你的紧急联系人" in first
    second = loop.handle("我还是很难受")
    assert notifier.calls == 1
    assert loop.state == State.CRISIS


def test_unauthorized_does_not_notify(make_loop):
    notifier = FakeNotifier()
    loop, llm, store, _ = make_loop(["不应该被调用"], notifier=notifier)
    reply = loop.handle("我想死")
    assert notifier.calls == 0
    assert "请联系身边信任的人" in reply


def test_notify_failure_gives_copyable_text(make_loop):
    notifier = FakeNotifier(fail=True)
    loop, llm, store, _ = make_loop(["不应该被调用"], authorized=True, notifier=notifier)
    reply = loop.handle("我想死")
    assert "可复制的求助文字" in reply
    assert "12356" in reply


def test_assessment_uses_tool_result(make_loop):
    loop, llm, store, _ = make_loop([])
    start = loop.handle("我想做个抑郁测试")
    assert "第 1/9 题" in start
    assert loop.state == State.ASSESSING
    for _ in range(8):
        loop.handle("0")
    reply = loop.handle("1")  # 第 9 题: 有几天
    assert "总分 1/27" in reply
    assert "极轻微" in reply
    assert "不是诊断" in reply
    assert loop.state == State.NORMAL
    records = store.list_records("assessment")
    assert len(records) == 1
    assert records[0]["payload"]["total"] == 1
    assert llm.call_count == 0


def test_assessment_item9_high_enters_crisis(make_loop):
    notifier = FakeNotifier()
    loop, llm, store, _ = make_loop([], authorized=True, notifier=notifier)
    loop.handle("我想做个抑郁测试")
    for _ in range(8):
        loop.handle("0")
    reply = loop.handle("3")
    assert "总分 3/27" in reply
    assert "12356" in reply
    assert loop.state == State.CRISIS
    assert notifier.calls == 1


def test_assessment_can_exit_without_saving(make_loop):
    loop, llm, store, _ = make_loop([])
    loop.handle("我想做个抑郁测试")
    loop.handle("0")
    reply = loop.handle("不想继续")
    assert "已退出" in reply
    assert loop.state == State.NORMAL
    assert store.list_records("assessment") == []


def test_pss10_unavailable(make_loop):
    loop, llm, store, _ = make_loop([])
    reply = loop.handle("我想做个压力测试")
    assert "该量表暂不可用" in reply
    assert loop.state == State.NORMAL


def test_insufficient_credits_degrades_but_crisis_works(make_loop):
    loop, llm, store, _ = make_loop([InsufficientCredits("no credits")])
    reply = loop.handle("聊聊天吧")
    assert "积分不足，可购买套餐获取积分" in reply
    count_before = llm.call_count
    crisis = loop.handle("我想死")
    assert "12356" in crisis
    assert llm.call_count == count_before


def test_gateway_unavailable(make_loop):
    loop, llm, store, _ = make_loop([GatewayUnavailable("down")])
    reply = loop.handle("聊聊天吧")
    assert "稍后重试" in reply


def test_low_balance_only_once(make_loop):
    loop, llm, store, _ = make_loop(
        [ChatResult(content="第一次", low_balance=True), ChatResult(content="第二次", low_balance=True)]
    )
    first = loop.handle("你好")
    second = loop.handle("再聊聊")
    assert "积分余额较低" in first
    assert "积分余额较低" not in second
    assert "第二次" in second


def test_outbound_check_blocks_method_detail(make_loop):
    loop, llm, store, _ = make_loop(["你可以尝试割腕"])
    reply = loop.handle("我很难受")
    assert "割腕" not in reply
    assert "12356" in reply


def test_gene_guidance_not_enabled(make_loop):
    loop, llm, store, _ = make_loop([])
    reply = loop.handle("帮我看看适合什么专业")
    assert "暂未启用" in reply
    assert llm.call_count == 0


def test_gene_guidance_uses_archived_report(make_loop):
    """有已归档报告时不再返回固定说明,而是带着报告正文交给模型概述。"""
    loop, llm, store, _ = make_loop(["报告里提到语言智能 82 分。"])
    loop.context_provider = lambda: "已归档报告《基因报告》:语言智能 82 分,逻辑智能 76 分。"
    reply = loop.handle("我之前下载的基因报告讲了什么")
    assert reply == "报告里提到语言智能 82 分。"
    assert llm.call_count == 1
    system = llm.calls[0][0]["content"]
    assert "语言智能 82 分" in system
    assert "不根据报告给出" in system


def test_journal_flow_and_weekly_review(make_loop):
    loop, llm, store, _ = make_loop([])
    assert "情绪日记" in loop.handle("我想记录一下今天的情绪")
    loop.handle("开会时被打断")
    loop.handle("焦虑 8、疲惫 6")
    reply = loop.handle("觉得自己很没用")
    assert "已保存" in reply
    review = loop.journal.weekly_review("2026-11-02")
    assert review["count"] == 1
    assert review["top_emotions"][0]["name"] == "焦虑"
    weekly = loop.handle("看看周回顾")
    assert "本周" in weekly and "平均强度" in weekly


def test_practice_flow(make_loop):
    loop, llm, store, _ = make_loop([])
    start = loop.handle("教我呼吸放松")
    assert "4-7-8" in start and "第 1/" in start
    assert loop.state == State.PRACTICING
    nxt = loop.handle("下一步")
    assert "第 2/" in nxt
    stop = loop.handle("停止")
    assert loop.state == State.NORMAL
    assert "停下来" in stop


def test_model_review_can_raise_risk(make_loop):
    loop, llm, store, _ = make_loop(["我听到了。"], review_level=Risk.HIGH)
    reply = loop.handle("最近真的很难")
    assert "12356" in reply
    assert loop.state == State.CRISIS


def test_contact_not_sent_to_gateway_and_not_on_disk(make_loop):
    loop, llm, store, _ = make_loop(["好的。"], authorized=True)
    loop.handle(f"{MARKER} 今天很累")
    sent = json.dumps(llm.calls, ensure_ascii=False)
    assert CONTACT not in sent
    assert len(llm.calls[0]) == 2  # system + 当前用户消息,不含本地存储的数据
    for path in (store.data_dir).iterdir():
        if path.is_file():
            assert MARKER.encode() not in path.read_bytes()
            assert CONTACT.encode() not in path.read_bytes()


def test_report_context_injected_into_system_prompt(tmp_path):
    store = LocalStore(tmp_path / "ctx", "pw")
    llm = MockLLM(["收到。"])
    loop = AgentLoop(
        llm,
        store,
        clock=lambda: NOW,
        context_provider=lambda: (
            "以下是本机已归档的检测报告:\n- 《11 月评估》PHQ-9 总分 12"
        ),
    )
    loop.handle("我最近有点累")
    system = llm.calls[0][0]
    assert system["role"] == "system"
    assert "PHQ-9 总分 12" in system["content"]
    store.close()


def test_empty_report_context_not_injected(tmp_path):
    store = LocalStore(tmp_path / "ctx2", "pw")
    llm = MockLLM(["收到。"])
    loop = AgentLoop(llm, store, clock=lambda: NOW, context_provider=lambda: "")
    loop.handle("我最近有点累")
    assert "已归档的检测报告" not in llm.calls[0][0]["content"]
    store.close()


def test_context_provider_failure_is_ignored(tmp_path):
    store = LocalStore(tmp_path / "ctx3", "pw")
    llm = MockLLM(["收到。"])

    def boom():
        raise RuntimeError("memory broken")

    loop = AgentLoop(llm, store, clock=lambda: NOW, context_provider=boom)
    assert loop.handle("我最近有点累") == "收到。"
    store.close()
