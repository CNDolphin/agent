"""入会话前测评：草稿、完成校验、基因抽取、记忆注入与接口 gate。"""

from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from client.app import create_app
from client.onboarding import (
    GeneExtractError,
    OnboardingError,
    OnboardingRequired,
    OnboardingService,
    parse_gene_payload,
)
from client.profiles import RuntimeManager
from client.runtime import Runtime
from client.tests.support import (
    DEVICE_KEY,
    FakeGateway,
    FakeNotifier,
    answer_all,
    complete_onboarding,
    default_rankings,
    make_config,
)
from mhagent.store.db import LocalStore

TOKEN_HEADER = {"X-Local-Token": "secret-token"}
LAN_ADDRESS = ("192.168.1.9", 5000)


# ---- 服务层 ----
def _service(tmp_path, llm=None, nickname="小明"):
    data_dir = tmp_path / "data"
    store = LocalStore(data_dir, DEVICE_KEY)
    service = OnboardingService(store, llm or FakeGateway(None), data_dir, nickname=nickname)
    return service, store


def _make_runtime(tmp_path):
    data_dir = tmp_path / "data"
    runtime = Runtime(
        make_config(data_dir),
        data_dir,
        device_key=DEVICE_KEY,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    runtime.open()
    return runtime


def test_draft_survives_reload(tmp_path):
    service, store = _service(tmp_path)
    state = service.get()
    assert state["status"] == "draft"
    assert state["progress"]["done_items"] == 0

    service.save_answers({"1": 4, "3": 5, "2": 0})
    store.close()

    reopened, store2 = _service(tmp_path)
    state = reopened.get()
    assert state["answers"] == {"1": 4, "3": 5}
    assert state["progress"]["done_items"] == 2
    store2.close()


def test_rankings_partial_then_full(tmp_path):
    service, store = _service(tmp_path)
    service.save_rankings({"intel": ["lang"]})
    state = service.get()
    assert state["rankings"]["intel"] == ["lang"]
    assert state["progress"]["intel_ranked"] is False

    with pytest.raises(OnboardingError):
        service.save_rankings({"intel": ["lang", "lang"]})
    with pytest.raises(OnboardingError):
        service.save_rankings({"intel": ["unknown"]})
    store.close()


def test_complete_requires_enough_answers(tmp_path):
    service, store = _service(tmp_path)
    service.save_answers({"1": 4})
    service.save_rankings(default_rankings(_runtime_proxy(service)))
    with pytest.raises(OnboardingError):
        service.complete()
    store.close()


class _runtime_proxy:
    """让 support 里的辅助函数能复用服务实例。"""

    def __init__(self, service):
        self.onboarding = service

    def save_onboarding_answers(self, answers):
        return self.onboarding.save_answers(answers)

    def save_onboarding_rankings(self, rankings):
        return self.onboarding.save_rankings(rankings)

    def complete_onboarding(self):
        return self.onboarding.complete()


def test_complete_requires_rankings(tmp_path):
    service, store = _service(tmp_path)
    service.save_answers({str(q["id"]): 4 for q in service.bank.questions if not q["reverse"]})
    with pytest.raises(OnboardingError):
        service.complete()
    store.close()


def test_complete_builds_memory(tmp_path):
    service, store = _service(tmp_path)
    proxy = _runtime_proxy(service)
    answer_all(proxy, 4)
    service.save_rankings(default_rankings(proxy))
    outcome = service.complete()

    assert service.get()["status"] == "completed"
    assert len(outcome["result"]["intel"]) == 8
    assert len(outcome["result"]["ind"]) == 40
    assert not outcome["memory_text"].startswith("【基础测评记忆】")  # 前缀由运行时注入
    assert "八大智能" in outcome["memory_text"]
    assert "不是诊断结论" in outcome["memory_text"]
    assert service.memory_text() == outcome["memory_text"]
    # 重复调用保持幂等
    again = service.complete()
    assert again["memory_text"] == outcome["memory_text"]
    store.close()


def test_ensure_ready_gate(tmp_path):
    service, store = _service(tmp_path)
    with pytest.raises(OnboardingRequired):
        service.ensure_ready()
    store.close()


# ---- 基因报告 ----
def test_parse_gene_payload_accepts_code_fence():
    payload = parse_gene_payload(
        '```json\n{"scores":{"lang":80,"logic":70,"visual":60,"nature":50,'
        '"music":40,"body":30,"social":20,"inner":10},"confidence":"high","notes":"x"}\n```'
    )
    assert payload["scores"]["lang"] == 80
    assert payload["confidence"] == "high"


def test_parse_gene_payload_rejects_incomplete():
    with pytest.raises(GeneExtractError):
        parse_gene_payload("这不是 JSON")
    with pytest.raises(GeneExtractError):
        parse_gene_payload('{"scores":{"lang":80}}')
    with pytest.raises(GeneExtractError):
        parse_gene_payload('{"error":"unrecognized"}')


def test_attach_gene_with_fake_llm(tmp_path):
    responses = {
        "scores": {iid: 72 for iid in ("lang", "logic", "visual", "nature", "music", "body", "social", "inner")},
        "confidence": "medium",
        "notes": "报告第 2 页",
    }
    service, store = _service(tmp_path)
    service.llm.reply = json.dumps(responses, ensure_ascii=False)

    gene = service.attach_gene(
        "先天能力评估报告：语言 72 分、逻辑数学 70 分、视觉空间 68 分".encode(),
        "基因报告.txt",
    )
    assert gene["confidence"] == "medium"
    assert gene["scores"]["lang"] == 72
    assert service.get()["gene"]["filename"] == "基因报告.txt"
    saved = list((tmp_path / "data" / "uploads" / "gene").glob("*"))
    assert len(saved) == 2  # 原文 + 抽取文本
    store.close()


def test_attach_gene_rejects_type_and_size(tmp_path):
    service, store = _service(tmp_path)
    with pytest.raises(OnboardingError):
        service.attach_gene(b"x", "report.exe")
    with pytest.raises(OnboardingError):
        service.attach_gene(b"x" * (10 * 1024 * 1024 + 1), "report.txt")
    with pytest.raises(GeneExtractError):
        service.attach_gene(b"short", "report.txt")
    store.close()


def test_attach_gene_llm_failure(tmp_path):
    service, store = _service(tmp_path)
    service.llm.reply = "抱歉，我无法识别"
    with pytest.raises(GeneExtractError):
        service.attach_gene("这是一份很长的基因检测报告文本内容，用于测试解析失败".encode(), "r.txt")
    assert service.get()["gene"] is None
    store.close()


# ---- 接口 ----
def _build(tmp_path, *, lan=False):
    config = make_config(tmp_path / "data", lan=lan)
    manager = RuntimeManager(
        config,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=True)
    client = TestClient(app, client=LAN_ADDRESS) if lan else TestClient(app)
    return client, manager


def test_api_questionnaire_and_draft(tmp_path):
    client, manager = _build(tmp_path)
    state = client.get("/api/onboarding", headers=TOKEN_HEADER).json()
    assert state["status"] == "draft"

    bank = client.get("/api/onboarding/questionnaire", headers=TOKEN_HEADER).json()
    assert len(bank["questions"]) == 80
    assert len(bank["intelligences"]) == 8

    saved = client.put(
        "/api/onboarding/answers", headers=TOKEN_HEADER, json={"answers": {"1": 5}}
    ).json()
    assert saved["answers"] == {"1": 5}
    assert saved["progress"]["done_items"] == 1
    manager.close()


def test_api_chat_blocked_until_complete(tmp_path):
    client, manager = _build(tmp_path)
    response = client.post("/api/chat", headers=TOKEN_HEADER, json={"text": "你好"})
    assert response.status_code == 409
    assert response.json()["code"] == "onboarding_required"

    complete_onboarding(manager.main())
    response = client.post("/api/chat", headers=TOKEN_HEADER, json={"text": "你好"})
    assert response.status_code == 200
    assert response.json()["reply"] == "我在听。"
    manager.close()


def test_api_device_token_blocked_until_complete(tmp_path):
    client, manager = _build(tmp_path, lan=True)
    manager.create_profile("孩子", "kid_01", "password-1")
    login = client.post(
        "/api/device/login", json={"username": "kid_01", "password": "password-1"}
    ).json()
    token = login["device_token"]
    header = {"X-Device-Token": token}

    response = client.post("/api/chat", headers=header, json={"text": "你好"})
    assert response.status_code == 409

    complete_onboarding(manager.runtime_for(login["profile"]["id"]))
    assert client.post("/api/chat", headers=header, json={"text": "你好"}).status_code == 200
    manager.close()


def test_api_gene_upload_and_complete(tmp_path):
    client, manager = _build(tmp_path)
    runtime = manager.main()
    runtime.gateway.reply = json.dumps(
        {
            "scores": {iid: 70 for iid in runtime.onboarding.bank.intel_ids},
            "confidence": "low",
            "notes": "测试",
        }
    )
    content = base64.b64encode("基因检测报告：语言 70 分，逻辑 70 分".encode()).decode()
    response = client.post(
        "/api/onboarding/gene",
        headers=TOKEN_HEADER,
        json={"filename": "gene.txt", "content": content},
    )
    assert response.status_code == 200
    assert response.json()["gene"]["scores"]["lang"] == 70

    bad = client.post(
        "/api/onboarding/gene",
        headers=TOKEN_HEADER,
        json={"filename": "gene.exe", "content": content},
    )
    assert bad.status_code == 400

    assert client.delete("/api/onboarding/gene", headers=TOKEN_HEADER).json()["gene"] is None

    answer_all(runtime)
    runtime.save_onboarding_rankings(default_rankings(runtime))
    completed = client.post("/api/onboarding/complete", headers=TOKEN_HEADER).json()
    assert "memory_text" in completed
    assert len(completed["result"]["intel"]) == 8
    manager.close()


def test_memory_injected_into_context(tmp_path):
    runtime = _make_runtime(tmp_path)
    complete_onboarding(runtime)
    context = runtime.loop._context_text("我语言能力怎么样")
    assert context
    assert context.startswith("【基础测评记忆】")
    assert "八大智能" in context
    runtime.close()


def test_profile_isolation_gate(tmp_path):
    client, manager = _build(tmp_path)
    complete_onboarding(manager.main())
    kid = manager.create_profile("孩子", "kid_01", "password-1")
    kid_runtime = manager.runtime_for(kid["id"])
    with pytest.raises(OnboardingRequired):
        kid_runtime.chat("你好")
    assert manager.main().onboarding_state()["status"] == "completed"
    manager.close()
