"""多元智能解读报告：接口契约、分析引擎与视角转换。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from client.app import create_app
from client.profiles import RuntimeManager
from client.tests.support import (
    FakeGateway,
    FakeNotifier,
    complete_onboarding,
    make_config,
)
from mhagent.mi.report import analyze_report, build_meta
from mhagent.mi.topics import subject_tune

TOKEN_HEADER = {"X-Local-Token": "secret-token"}
LAN_ADDRESS = ("192.168.1.9", 5000)


def build(tmp_path, *, lan=False):
    config = make_config(tmp_path / "data", lan=lan)
    manager = RuntimeManager(
        config,
        gateway_factory=FakeGateway,
        notifier_factory=lambda consent, session: FakeNotifier(),
    )
    app = create_app(manager, "secret-token", dev_mode=True)
    client = TestClient(app, client=LAN_ADDRESS) if lan else TestClient(app)
    return client, manager


def _result(manager) -> dict:
    return manager.runtime_for().onboarding_state()["result"]


def test_requires_completed_assessment(tmp_path):
    client, manager = build(tmp_path)
    response = client.get(
        "/api/profiles/main/interpretation-report", headers=TOKEN_HEADER
    )
    assert response.status_code == 409
    assert response.json()["code"] == "onboarding_required"
    manager.close()


def test_renders_full_report(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())

    response = client.get(
        "/api/profiles/main/interpretation-report", headers=TOKEN_HEADER
    )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    html = body["html"]
    assert html.count('<section class="sec"') == 17
    for marker in (
        "八大智能总览（天赋雷达）",
        "分数判定与反转提示",
        "40 项核心指标逐项解读",
        "十七、专题解读模块",
        "十六、总结 · 接下来该怎么做",
    ):
        assert marker in html
    assert body["meta"]["name"] == "我"
    manager.close()


def test_profile_isolation(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())
    created = manager.create_profile("孩子", "kid_01", "password-1")

    response = client.get(
        f"/api/profiles/{created['id']}/interpretation-report", headers=TOKEN_HEADER
    )
    assert response.status_code == 409
    assert response.json()["code"] == "onboarding_required"
    assert (
        client.get(
            "/api/profiles/main/interpretation-report", headers=TOKEN_HEADER
        ).status_code
        == 200
    )
    manager.close()


def test_lan_device_denied(tmp_path):
    client, manager = build(tmp_path, lan=True)
    manager.create_profile("孩子", "kid_01", "password-1")
    token = client.post(
        "/api/device/login", json={"username": "kid_01", "password": "password-1"}
    ).json()["device_token"]

    response = client.get(
        "/api/profiles/main/interpretation-report",
        headers={"X-Device-Token": token},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "desktop_only"
    manager.close()


def test_query_options_applied(tmp_path):
    client, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())
    response = client.get(
        "/api/profiles/main/interpretation-report",
        headers=TOKEN_HEADER,
        params={"age": "10", "gender": "男", "edition": "edu", "who": "kid", "purpose": "study"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {
        "name": "我",
        "age": "10",
        "gender": "男",
        "edition": "edu",
        "who": "kid",
        "purpose": "study",
        "job": "",
        "note": "",
        "mode": "interpreter",
    }
    assert "10 岁" in body["html"]
    assert "学业规划" in body["html"]
    manager.close()


def test_analyze_report_shape(tmp_path):
    _, manager = build(tmp_path)
    complete_onboarding(manager.runtime_for())
    result = _result(manager)
    meta = build_meta({"nickname": "小明", "age_range": "9-11"}, {})

    report = analyze_report(result, meta)
    assert len(report["intelScores"]) == 8
    assert len(report["scores"]) == 40
    assert len(report["diagonals"]) == 4
    assert len(report["wudao"]) == 5
    assert len(report["rank"]) == 8
    assert report["rank"][0]["rank"] == 1
    assert report["topics"]
    assert all(topic["id"] for topic in report["topics"])
    manager.close()


def test_subject_tune_self_view():
    html = "<p>孩子适合用优势带动弱势，别人家孩子不必比较，请勿用性别框住孩子。</p>"
    tuned = subject_tune(html, "me")
    assert "你适合用优势带动弱势" in tuned
    assert "别人家孩子" in tuned
    assert "请勿让性别期待框住自己" in tuned
    assert subject_tune(html, "kid") == html
