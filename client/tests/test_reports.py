"""检测报告本地归档、同步与通知订阅测试。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from client.app import create_app
from client.notifications import ReportStream
from client.profiles import RuntimeManager
from client.reports import ReportService, ReportStore, safe_filename, unique_path
from client.runtime import Runtime
from client.tests.support import DEVICE_KEY, FakeGateway, FakeNotifier, make_config
from mhagent.store.db import LocalStore

TOKEN_HEADER = {"X-Local-Token": "secret-token"}


class FakeReportGateway(FakeGateway):
    """在 FakeGateway 上补充报告接口。"""

    def __init__(self, session, **kwargs):
        super().__init__(session, **kwargs)
        self.pending: list[dict] = []
        self.downloads: list[int] = []
        self.read: list[int] = []
        self.fail_ids: set[int] = set()

    def list_pending_reports(self):
        return list(self.pending)

    def download_report(self, report_id):
        if int(report_id) in self.fail_ids:
            raise RuntimeError("mock download failure")
        self.downloads.append(int(report_id))
        return f"report-{report_id}.pdf", f"content-{report_id}".encode(), "application/pdf"

    def mark_report_read(self, report_id):
        self.read.append(int(report_id))

    def stream_report_events(self):
        return iter(())


def make_store(tmp_path):
    return LocalStore(tmp_path / "data", DEVICE_KEY)


def make_service(tmp_path, gateway):
    store = make_store(tmp_path)
    service = ReportService(gateway, store, tmp_path / "data")
    return store, service


def test_safe_filename_strips_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..\\..\\windows\\x.pdf") == "x.pdf"
    assert safe_filename("") == "report"
    assert safe_filename("..") == "report"
    assert safe_filename("report\x00.pdf") == "report.pdf"
    long_name = "a" * 200 + ".pdf"
    cleaned = safe_filename(long_name)
    assert len(cleaned) <= 120
    assert cleaned.endswith(".pdf")


def test_unique_path_appends_suffix(tmp_path):
    first = unique_path(tmp_path, "a.pdf")
    first.write_bytes(b"x")
    second = unique_path(tmp_path, "a.pdf")
    assert second.name == "a-1.pdf"


def test_report_store_saves_and_marks_read(tmp_path):
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")

    entry = reports.save(
        {"report_id": 5, "filename": "../../报告.pdf", "title": "测评", "version": 2},
        b"pdf-bytes",
    )
    path = tmp_path / "data" / entry["path"]
    assert path.is_file()
    assert path.read_bytes() == b"pdf-bytes"
    assert path.parent == tmp_path / "data" / "documents"
    assert reports.has(5)
    assert reports.unread_count() == 1
    assert reports.list()[0]["version"] == 2
    absolute = reports.list()[0]["abs_path"]
    assert absolute.endswith("documents/报告.pdf")
    assert Path(absolute).is_file()

    read_entry = reports.mark_read(5)
    assert read_entry["read_at"]
    assert read_entry["abs_path"] == absolute
    assert reports.unread_count() == 0
    # 重复标记不改变时间
    assert reports.mark_read(5)["read_at"] == read_entry["read_at"]

    records = store.list_records("report")
    assert len(records) == 1
    assert records[0]["payload"]["report_id"] == 5
    store.close()


def test_sync_pending_downloads_once(tmp_path):
    store = make_store(tmp_path)
    gateway = FakeReportGateway(None)
    gateway.pending = [
        {"report_id": 1, "version": 1, "title": "报告一", "filename": "one.pdf"},
        {"report_id": 2, "version": 1, "title": "报告二", "filename": "two.pdf"},
    ]
    service = ReportService(gateway, store, tmp_path / "data")

    result = service.sync_pending()
    assert result["synced"] == 2
    assert gateway.downloads == [1, 2]
    assert service.unread_count() == 2

    again = service.sync_pending()
    assert again["synced"] == 0
    assert gateway.downloads == [1, 2]
    store.close()


def test_sync_pending_skips_failed_items(tmp_path):
    store = make_store(tmp_path)
    gateway = FakeReportGateway(None)
    gateway.pending = [
        {"report_id": 1, "version": 1, "title": "ok"},
        {"report_id": 2, "version": 1, "title": "bad"},
    ]
    gateway.fail_ids = {2}
    service = ReportService(gateway, store, tmp_path / "data")

    result = service.sync_pending()
    assert result["synced"] == 1
    assert [item["report_id"] for item in result["items"]] == [1]
    store.close()


def test_mark_read_calls_gateway(tmp_path):
    store, service = make_service(tmp_path, FakeReportGateway(None))
    service.reports.save({"report_id": 9, "filename": "x.pdf", "title": "x"}, b"1")

    entry = service.mark_read(9)

    assert entry["read_at"]
    assert service.gateway.read == [9]
    store.close()


def test_report_stream_dispatches_event():
    gateway = FakeReportGateway(None)
    received: list[dict] = []
    stop = threading.Event()

    def on_event(event):
        received.append(event)
        stop.set()

    stream = ReportStream(gateway, on_event, stop_event=stop)
    stream._dispatch({"event": "report.created", "data": {"report_id": 3}})
    assert received == [{"event": "report.created", "data": {"report_id": 3}}]
    # 非报告事件被忽略
    stream._dispatch({"event": "other", "data": {}})
    assert len(received) == 1


def test_report_stream_reconnects_with_backoff():
    attempts = []
    stop = threading.Event()

    class FlakyGateway:
        def stream_report_events(self):
            attempts.append(1)
            if len(attempts) >= 3:
                stop.set()
            raise RuntimeError("断线")

    stream = ReportStream(FlakyGateway(), lambda event: None, backoff=(0.01,), stop_event=stop)
    stream._run()

    assert len(attempts) == 3


def test_sub_profile_does_not_sync_reports(tmp_path):
    data_dir = tmp_path / "sub"
    runtime = Runtime(
        make_config(data_dir),
        data_dir,
        profile={"id": "sub1", "role": "sub", "nickname": "子档案"},
        device_key=DEVICE_KEY,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    runtime.open()

    assert runtime.list_reports() == {"items": [], "unread": 0}
    assert runtime.sync_reports() == {"synced": 0, "items": []}
    assert runtime.unread_report_count() == {"count": 0}
    assert runtime.report_stream is None

    runtime.close()


class FakeStream:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self, timeout=None):
        self.stopped = True


def test_main_profile_stream_starts_after_login_and_stops_on_logout(tmp_path):
    data_dir = tmp_path / "data"
    created: list[FakeStream] = []

    def factory(gateway, on_event):
        stream = FakeStream()
        created.append(stream)
        return stream

    runtime = Runtime(
        make_config(data_dir),
        data_dir,
        device_key=DEVICE_KEY,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
        report_stream_factory=factory,
    )
    runtime.open()
    # 未登录时不建连接
    assert created == []

    runtime.login_password("13800138000", "correct-horse")
    assert len(created) == 1
    assert created[0].started is True

    runtime.logout()
    assert created[0].stopped is True
    assert runtime.report_stream is None

    runtime.close()


def test_local_api_exposes_reports(tmp_path):
    config = make_config(tmp_path / "data")
    manager = RuntimeManager(
        config,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=True)
    client = TestClient(app)

    main = manager.main()

    listed = client.get("/api/reports", headers=TOKEN_HEADER)
    assert listed.status_code == 200
    assert listed.json() == {"items": [], "unread": 0}

    unread = client.get("/api/reports/unread-count", headers=TOKEN_HEADER)
    assert unread.json() == {"count": 0}

    synced = client.post("/api/reports/sync", headers=TOKEN_HEADER)
    assert synced.status_code == 200
    assert synced.json()["synced"] == 0

    missing = client.get("/api/reports/999/file", headers=TOKEN_HEADER)
    assert missing.status_code == 404

    manager.close()


@pytest.mark.parametrize("name", ["a.pdf", "b.png"])
def test_local_report_file_returns_attachment(tmp_path, name):
    config = make_config(tmp_path / "data")
    manager = RuntimeManager(
        config,
        gateway_factory=FakeReportGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=True)
    client = TestClient(app)

    main = manager.main()
    main.reports.reports.save({"report_id": 21, "filename": name, "title": "报告"}, b"payload")

    response = client.get("/api/reports/21/file", headers=TOKEN_HEADER)
    assert response.status_code == 200
    assert response.content == b"payload"

    read = client.post("/api/reports/21/read", headers=TOKEN_HEADER)
    assert read.status_code == 200
    assert read.json()["unread"] == 0

    manager.close()


def _docx_bytes(text: str) -> bytes:
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_paragraph("心理健康检测报告")
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _docx_paragraphs(paragraphs: list[str]) -> bytes:
    from io import BytesIO

    from docx import Document

    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_report_memory_extracts_docx_text(tmp_path):
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    service = ReportService(FakeReportGateway(None), store, tmp_path / "data")
    reports.save(
        {
            "report_id": 11,
            "filename": "评估.docx",
            "title": "11 月情绪评估",
            "created_at": "2026-11-12T08:00:00+00:00",
        },
        _docx_bytes("PHQ-9 总分 12 分,中度抑郁倾向,建议规律作息。"),
    )

    memory = reports.memory_items()
    assert len(memory) == 1
    assert "12 分" in memory[0]["excerpt"]

    text = service.context_text()
    assert "本机已下载保存的检测报告文件" in text
    assert "11 月情绪评估" in text
    assert "PHQ-9 总分 12 分" in text
    assert "documents/评估.docx" in text
    store.close()


def test_report_memory_marks_images_without_text(tmp_path):
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    service = ReportService(FakeReportGateway(None), store, tmp_path / "data")
    reports.save(
        {
            "report_id": 12,
            "filename": "scan.png",
            "title": "图片报告",
            "created_at": "2026-11-12T09:00:00+00:00",
        },
        b"\x89PNG\r\n\x1a\nfake",
    )

    assert reports.memory_items()[0]["excerpt"] == ""
    text = service.context_text()
    assert "图片报告" in text
    assert "图片" in text
    assert "正文未提取" in text
    store.close()


def test_backfill_memory_restores_legacy_reports(tmp_path):
    """旧版本只写了 reports.state,没有记忆区;启动时应补写正文。"""
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    service = ReportService(FakeReportGateway(None), store, tmp_path / "data")
    reports.save(
        {
            "report_id": 31,
            "filename": "历史.docx",
            "title": "历史评估报告",
            "created_at": "2026-11-10T02:00:00+00:00",
        },
        _docx_bytes("焦虑自评总分 58 分,建议两周后复测。"),
    )
    # 模拟旧版本:清空记忆区,保留 state
    store.kv_set("reports.memory", {})

    assert reports.memory_items() == []
    assert service.backfill_memory() == 1

    memory = reports.memory_items()
    assert len(memory) == 1
    assert "总分 58 分" in memory[0]["excerpt"]
    text = service.context_text()
    assert "历史评估报告" in text
    assert "总分 58 分" in text
    # 幂等:再次回填不重复写入
    assert service.backfill_memory() == 0
    store.close()


def test_extract_report_text_keeps_key_values_beyond_intro(tmp_path):
    """关键数值在长文档后半段时也要提取到,不能只截开头。"""
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    paragraphs = ["前言内容,介绍检测背景与理论说明。"] * 60
    paragraphs += [
        "排序第一：肢体动觉智能 分数:71.77",
        "排序第二：人际沟通智能 分数:69.75",
    ]
    reports.save(
        {"report_id": 41, "filename": "智能.docx", "title": "基因报告"},
        _docx_paragraphs(paragraphs),
    )

    excerpt = reports.memory_items()[0]["excerpt"]
    assert "71.77" in excerpt
    assert "69.75" in excerpt
    store.close()


def test_refresh_memory_upgrades_old_excerpt(tmp_path):
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    service = ReportService(FakeReportGateway(None), store, tmp_path / "data")
    reports.save(
        {"report_id": 42, "filename": "old.docx", "title": "旧报告"},
        _docx_bytes("PHQ-9 总分 15 分。"),
    )
    memory = store.kv_get("reports.memory")
    memory["items"]["42"]["excerpt"] = ""
    memory["items"]["42"]["excerpt_version"] = 0
    store.kv_set("reports.memory", memory)

    assert service.refresh_memory() == 1
    assert "总分 15 分" in reports.memory_items()[0]["excerpt"]
    assert service.refresh_memory() == 0
    store.close()


def test_context_text_retrieves_sections_matching_question(tmp_path):
    """提问涉及八大智能时,应检索到报告后段的解读段落,而不是只给开头摘要。"""
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    service = ReportService(FakeReportGateway(None), store, tmp_path / "data")
    paragraphs = ["前言:本报告介绍检测的科学依据与理论基础。"] * 40
    paragraphs += [
        "排序第一：肢体动觉智能 分数:71.77 说明：你的身体协调与动作学习能力突出。",
        "排序第二：人际沟通智能 分数:69.75 说明：你善于理解他人情绪并建立关系。",
    ]
    reports.save(
        {"report_id": 51, "filename": "解读.docx", "title": "基因报告"},
        _docx_paragraphs(paragraphs),
    )

    text = service.context_text("对报告的八大智能进行解读")
    assert "肢体动觉智能" in text
    assert "71.77" in text
    assert "人际沟通智能" in text
    store.close()


def test_backfill_memory_skips_missing_files(tmp_path):
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    service = ReportService(FakeReportGateway(None), store, tmp_path / "data")
    entry = reports.save(
        {"report_id": 32, "filename": "gone.pdf", "title": "已删除的报告"},
        b"%PDF-1.4 fake",
    )
    store.kv_set("reports.memory", {})
    (tmp_path / "data" / entry["path"]).unlink()

    assert service.backfill_memory() == 0
    assert reports.memory_items() == []
    store.close()


def test_report_memory_keeps_latest_items(tmp_path):
    store = make_store(tmp_path)
    reports = ReportStore(store, tmp_path / "data")
    for index in range(1, 7):
        reports.save(
            {
                "report_id": index,
                "filename": f"r{index}.png",
                "title": f"报告{index}",
                "created_at": f"2026-11-{index:02d}T00:00:00+00:00",
            },
            b"\x89PNG\r\n\x1a\n",
        )

    memory = reports.memory_items()
    assert len(memory) == 5
    assert [item["report_id"] for item in memory] == [6, 5, 4, 3, 2]
    store.close()
