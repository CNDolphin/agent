import json
from datetime import datetime, timedelta

import httpx
import respx

from mhagent.auth_session import AuthSession, TokenPair
from mhagent.consent import ConsentStore
from mhagent.llm.gateway import GatewayClient
from mhagent.loop import AgentLoop, State
from mhagent.store.db import LocalStore
from mhagent.store.export import export_store, import_store

BASE = "http://gw.local"
CONTACT = "13900001111"
MARKER = "PRIVATE-MARKER-xyz"


def test_end_to_end(tmp_path):
    data_dir = tmp_path / "data"
    store = LocalStore(data_dir, "pw")
    session = AuthSession(store)
    session.save(TokenPair(access_token="token-xyz", refresh_token="refresh-xyz"))
    consent = ConsentStore(store)
    consent.agree("v2")
    consent.set_emergency_contact("sms", CONTACT, authorized=True)

    gateway = GatewayClient(BASE, session)
    loop = AgentLoop(gateway, store, consent=consent)

    with respx.mock:
        route = respx.post(f"{BASE}/llm/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": "我在听,你可以慢慢说。",
                    "usage": {"input_hit": 3, "input_miss": 4, "output": 5},
                    "cost": 2,
                    "balance": 98,
                },
            )
        )

        # 1. 普通对话
        reply = loop.handle(f"{MARKER} 最近有点累")
        assert "我在听" in reply
        assert route.call_count == 1

        # 2. 情绪日记
        loop.handle("我想记录一下今天的情绪")
        loop.handle("下班后被临时叫去开会")
        loop.handle("焦虑 7、疲惫 6")
        assert "已保存" in loop.handle("担心自己做不好")
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        assert loop.journal.weekly_review(week_start)["count"] == 1

        # 3. 评估(GAD-7,答案全部为 1 => 7 分,轻度)
        loop.handle("我想做个焦虑测试")
        for _ in range(6):
            loop.handle("1")
        result_text = loop.handle("1")
        assert "总分 7/21" in result_text
        assert "轻度" in result_text
        assert loop.state == State.NORMAL

        # 4. 高风险:不调用网关
        before = route.call_count
        crisis = loop.handle("我想死")
        assert "12356" in crisis
        assert route.call_count == before
        assert loop.state == State.CRISIS

    captured = json.dumps(
        [json.loads(call.request.content) for call in route.calls], ensure_ascii=False
    )
    assert CONTACT not in captured
    assert "token-xyz" not in captured
    assert "refresh-xyz" not in captured

    # 5. 加密导出与导入
    backup = tmp_path / "backup.enc"
    export_store(store, backup)
    raw = backup.read_text(encoding="utf-8")
    for secret in (MARKER, CONTACT, "token-xyz"):
        assert secret not in raw

    new_dir = tmp_path / "new"
    new_store = LocalStore(new_dir, "pw")
    counts = import_store(new_store, backup)
    assert counts["records"] == store.record_count()
    assert new_store.record_count() == store.record_count()

    # 6. 本地文件中没有明文隐私数据
    for directory in (data_dir, new_dir):
        for path in directory.iterdir():
            if path.is_file():
                assert MARKER.encode() not in path.read_bytes()
                assert CONTACT.encode() not in path.read_bytes()
                assert b"token-xyz" not in path.read_bytes()

    gateway.close()
    new_store.close()
    store.close()
