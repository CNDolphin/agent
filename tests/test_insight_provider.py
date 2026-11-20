import pytest

from mhagent.insight.provider import FeatureNotEnabled, NotEnabled, get_provider


def test_not_enabled_raises():
    provider = NotEnabled()
    assert provider.enabled is False
    with pytest.raises(FeatureNotEnabled):
        provider.import_report("report.pdf")
    with pytest.raises(FeatureNotEnabled):
        provider.get_dimensions("r1")
    with pytest.raises(FeatureNotEnabled):
        provider.guidance("r1", {})


def test_get_provider_returns_placeholder():
    provider = get_provider()
    assert provider.enabled is False
    with pytest.raises(FeatureNotEnabled):
        provider.import_report("x")
