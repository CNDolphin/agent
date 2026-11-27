"""报告提交、分数抽取与版本对比记忆测试。"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from client.app import create_app
from client.profiles import RuntimeManager
from client.reports import MAX_UPLOAD_BYTES, ReportService, build_analysis, extract_scores
from client.tests.support import DEVICE_KEY, FakeGateway, FakeNotifier, make_config
from mhagent.mi.quiz import QuestionBank
from mhagent.store.db import LocalStore

TOKEN_HEADER = {"X-Local-Token": "secret-token"}


class FakeReportGateway(FakeGateway):
    """报告接口的最小替身:不做后台推送。"""

    def __init__(self, session, **kwargs):
        super().__init__(session, **kwargs)
        self.read: list[int] = []

    def list_pending_reports(self):
        return []

    def download_report(self, report_id):
        raise AssertionError("测试不应下载后台报告")

    def mark_report_read(self, report_id):
        self.read.append(int(report_id))

    def stream_report_events(self):
        return iter(())


def _indicator_id(name: str) -> str:
    bank = QuestionBank.load()
    return next(
        ind["id"] for item in bank.intelligences for ind in item["indicators"] if ind["name"] == name
    )


def make_service(tmp_path, baseline=None):
    store = LocalStore(tmp_path / "data", DEVICE_KEY)
    service = ReportService(
        FakeReportGateway(None),
        store,
        tmp_path / "data",
        baseline_provider=(lambda: baseline) if baseline else None,
    )
    return service


def test_extract_scores_reads_intel_and_indicator_names():
    scores = extract_scores(
        "八大智能:语言智能 82,逻辑数学智能 64;阅读能力 71,归纳能力 58。"
    )
    assert scores["intel"]["lang"] == 82
    assert scores["intel"]["logic"] == 64
    assert scores["ind"][_indicator_id("阅读能力")] == 71
    assert scores["ind"][_indicator_id("归纳能力")] == 58


def test_extract_scores_skips_toc_and_reads_gene_report_tables():
    text = """
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
口语能力 115.17
感受能力 1 4.43 12.56%
"""
    scores = extract_scores(text)
    assert scores["intel"]["visual"] == 72
    assert scores["intel"]["lang"] == 62
    assert scores["intel"]["body"] == 54
    # 40 项优先取优势值表，按 1.5 归一化到 0-100。
    assert scores["ind"][_indicator_id("阅读能力")] == 81


def test_build_analysis_marks_rise_fall_and_baseline():
    current = {
        "report_id": -1,
        "title": "新报告",
        "received_at": "2026-11-27T10:00:00+00:00",
        "scores": {
            "intel": {"lang": 74, "logic": 71, "visual": 62, "nature": 66, "music": 58},
            "ind": {_indicator_id("阅读能力"): 72},
        },
    }
    previous = {
        "report_id": 7,
        "title": "旧报告",
        "received_at": "2026-06-01T10:00:00+00:00",
        "scores": {
            "intel": {"lang": 82, "logic": 62, "visual": 62, "nature": 66, "music": 58},
            "ind": {_indicator_id("阅读能力"): 85},
        },
    }
    baseline = {
        "intel": {
            "lang": {"score": 80},
            "logic": {"score": 60},
            "visual": {"score": 61},
        }
    }
    text = build_analysis(current, previous, baseline)
    assert "上升" in text and "回落" in text
    assert "指标变化" in text and "阅读能力 85→72(-13)" in text
    assert "整体方向一致" in text
    assert "不是诊断" in text


def test_upload_writes_analysis_into_context(tmp_path):
    service = make_service(tmp_path)
    first = service.upload(
        "语言智能 82 逻辑数学智能 70 阅读能力 80 归纳能力 58".encode("utf-8"),
        "report.txt",
        "第一次报告",
    )
    assert first["item"]["report_id"] < 0
    assert "第一份" in first["analysis"] and "基线" in first["analysis"]
    assert len(first["analysis"]) <= 200
    stored = service.reports.analysis()["text"]
    assert "已记入长期记忆" in stored
    assert "这是第一份报告" in stored

    context = service.context_text()
    assert "报告对比分析" in context
    assert "第一次报告" in context

    second = service.upload(
        "语言智能 90 逻辑数学智能 60 阅读能力 65 归纳能力 70".encode("utf-8"),
        "report2.txt",
        "第二次报告",
    )
    assert "和上次的" in second["analysis"]
    assert "涨" in second["analysis"] or "降" in second["analysis"]
    assert "不是诊断" not in second["analysis"]


def test_upload_rejects_bad_type_and_size(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(ValueError):
        service.upload(b"x", "report.png")
    with pytest.raises(ValueError):
        service.upload(b"x" * (MAX_UPLOAD_BYTES + 1), "report.txt")


def test_upload_route_records_memory(tmp_path):
    config = make_config(tmp_path / "data")
    manager = RuntimeManager(
        config,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    client = TestClient(create_app(manager, "secret-token", dev_mode=True))
    manager.main()

    payload = {
        "filename": "report.txt",
        "title": "接口报告",
        "content": base64.b64encode("语言智能 82 阅读能力 71".encode("utf-8")).decode("ascii"),
    }
    response = client.post("/api/reports/upload", headers=TOKEN_HEADER, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["item"]["report_id"] < 0
    assert body["analysis"]
    assert body["unread"] == 0

    bad = client.post(
        "/api/reports/upload",
        headers=TOKEN_HEADER,
        json={"filename": "a.png", "content": base64.b64encode(b"x").decode("ascii")},
    )
    assert bad.status_code == 400

    manager.close()
