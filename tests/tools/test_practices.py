import pytest

from mhagent.tools.practices import (
    get_cbt_template,
    get_cbt_template_detail,
    get_practice,
    knowledge_topics,
    list_cbt_templates,
    list_practices,
    pick_knowledge,
)

PRACTICES = ["breathing_478", "box_breathing", "body_scan", "grounding_54321"]
TEMPLATES = ["thought_record", "distortion_check", "behavioral_activation", "problem_solving"]


@pytest.mark.parametrize("practice_id", PRACTICES)
def test_practice_structure(practice_id):
    data = get_practice(practice_id)
    assert data["steps"]
    for step in data["steps"]:
        assert step["instruction"]
        assert isinstance(step["seconds"], int) and step["seconds"] > 0
    assert data["duration_seconds"] > 0
    assert data["stop_hint"]


def test_all_practices_listed():
    assert set(list_practices()) == set(PRACTICES)


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_cbt_templates(template_id):
    fields = get_cbt_template(template_id)
    assert isinstance(fields, list) and fields
    detail = get_cbt_template_detail(template_id)
    assert detail["name"]
    assert detail["summary"]


def test_unknown_ids():
    with pytest.raises(KeyError):
        get_practice("unknown")
    with pytest.raises(KeyError):
        get_cbt_template("unknown")


def test_knowledge():
    topics = knowledge_topics()
    assert len(topics) >= 4
    total = 0
    for topic in topics:
        items = pick_knowledge(topic)
        assert items
        for item in items:
            assert item["title"] and item["body"] and item["source"]
            total += 1
    assert 15 <= total <= 20
    assert pick_knowledge("unknown") == []
