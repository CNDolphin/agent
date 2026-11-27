"""会话提交报告后实时修正解读报告，并让后续对话以报告为准。"""

from __future__ import annotations

import base64

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

GENE_TEXT = """
目录
语言智能分析 20
逻辑数学智能分析 21
视觉空间智能分析 22
自然观察智能分析 23
音乐智能分析 24
肢体动觉智能分析 25
人际沟通智能分析 26
个人内省智能分析 27
排序第一：视觉空间智能 分数:71.98
排序第二：逻辑数学智能 分数：70.76
排序第三：自然观察智能 分数：65.61
排序第四：人际沟通智能 分数：63.44
排序第五：音乐智能 分数：62.38
排序第六：语言智能 分数：62.15
排序第七：个人内省智能 分数：61.21
排序第八：肢体动觉智能 分数：54.48
阅读能力 121.73
"""


class FakeReportGateway(FakeGateway):
    """报告接口替身：不推送、不下载后台报告。"""

    def list_pending_reports(self):
        return []

    def download_report(self, report_id):
        raise AssertionError("测试不应下载后台报告")

    def mark_report_read(self, report_id):
        return None

    def stream_report_events(self):
        return iter(())


def build(tmp_path):
    config = make_config(tmp_path / "data")
    manager = RuntimeManager(
        config,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    client = TestClient(create_app(manager, "secret-token", dev_mode=True))
    return client, manager


def upload(client, text: str, *, revise: bool, title: str = "基因报告"):
    payload = {
        "filename": "gene.txt",
        "title": title,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "revise_interpretation": revise,
    }
    return client.post("/api/reports/upload", headers=TOKEN_HEADER, json=payload)


def test_upload_revision_overrides_assessment_and_memory(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())

    response = upload(client, "语言智能 95，逻辑数学智能 88", revise=True)
    assert response.status_code == 200
    body = response.json()
    revision = body["interpretation"]
    assert revision["revised"] is True
    assert revision["coverage"]["intel"] == 2
    assert "解读报告已按这份报告修正" in revision["note"]
    assert body["scores"]["intel"]["lang"] == 95

    state = manager.runtime_for().onboarding_state()
    assert state["result"]["fusion_version"] == "REPORT-OVERRIDE"
    assert state["result"]["gene_used"] is False
    assert state["result"]["intel"]["lang"]["score"] == 95.0
    assert state["interpretation"]["source"]["kind"] == "report"

    memory = state["memory_text"]
    assert "【解读报告要点】" in memory
    assert "会话提交报告《基因报告》" in memory
    assert "自评问卷与基因融合不再参与" in memory

    report = client.get(
        "/api/profiles/main/interpretation-report", headers=TOKEN_HEADER
    ).json()
    assert report["source"]["kind"] == "report"
    assert report["source"]["title"] == "基因报告"
    assert "数据来源 · 会话提交报告《基因报告》" in report["html"]
    assert "三源融合说明" not in report["html"]
    manager.close()


def test_upload_without_flag_keeps_assessment(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())
    before = manager.runtime_for().onboarding_state()["result"]

    response = upload(client, "语言智能 95", revise=False)
    assert response.status_code == 200
    assert "interpretation" not in response.json()

    state = manager.runtime_for().onboarding_state()
    assert state["result"]["fusion_version"] == before["fusion_version"]
    assert state["result"]["intel"]["lang"]["score"] == before["intel"]["lang"]["score"]
    manager.close()


def test_revision_requires_completed_assessment(tmp_path):
    client, manager = build(tmp_path)
    manager.main()

    response = upload(client, "语言智能 95", revise=True)
    assert response.status_code == 200
    revision = response.json()["interpretation"]
    assert revision["revised"] is False
    assert "尚未完成基础测评" in revision["note"]
    manager.close()


def test_ensure_interpretation_backfills_legacy_record(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())
    runtime = manager.runtime_for()
    records = runtime.store.list_records("mi_assessment")
    payload = dict(records[0]["payload"])
    payload["interpretation"] = None
    payload["memory_text"] = ""
    runtime.store.update_record(records[0]["id"], payload)

    runtime.onboarding.ensure_interpretation()
    state = runtime.onboarding.get()
    assert state["interpretation"]["version"] == "REPORT-DIGEST-1.0"
    assert "【解读报告要点】" in state["memory_text"]
    manager.close()


def test_gene_report_upload_uses_gene_fusion(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())

    response = upload(client, GENE_TEXT, revise=True)
    assert response.status_code == 200
    body = response.json()
    revision = body["interpretation"]
    assert revision["revised"] is True
    assert revision["mode"] == "gene"

    state = manager.runtime_for().onboarding_state()
    result = state["result"]
    assert result["gene_used"] is True
    assert result["fusion_version"] == "FUSION-1.0"
    assert state["gene"]["scores"]["visual"] == 72
    assert state["gene"]["report_id"] == body["item"]["report_id"]
    assert "report_override" not in state
    assert "【基因来源】" in state["memory_text"]

    report = client.get(
        "/api/profiles/main/interpretation-report", headers=TOKEN_HEADER
    ).json()
    assert report["source"]["kind"] == "assessment"
    assert "基因报告" in report["source"]["label"]
    assert "三源融合说明" in report["html"]
    assert "基因分" in report["html"]
    manager.close()


def test_generate_report_refreshes_from_uploaded_gene_report(tmp_path):
    client, manager = build(tmp_path)
    runtime = manager.runtime_for()
    complete_onboarding(runtime)
    # 先只归档基因报告，不上报修正。
    upload(client, GENE_TEXT, revise=False)

    # 模拟历史错误：用目录页码覆盖成了 REPORT-OVERRIDE。
    bad = {intel_id: 20 for intel_id in runtime.onboarding.bank.intel_ids}
    runtime.onboarding.apply_report_scores({"intel": bad, "ind": {}})
    assert runtime.onboarding.get()["result"]["fusion_version"] == "REPORT-OVERRIDE"

    # 打开解读报告即自动修复，无需先手动点击「生成报告」。
    response = client.get(
        "/api/profiles/main/interpretation-report", headers=TOKEN_HEADER
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"]["kind"] == "assessment"
    assert "三源融合说明" in body["html"]

    state = runtime.onboarding_state()
    assert state["result"]["gene_used"] is True
    assert state["result"]["fusion_version"] == "FUSION-1.0"
    assert state["gene"]["scores"]["visual"] == 72
    assert "report_override" not in state
    manager.close()
