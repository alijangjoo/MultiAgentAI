"""Tests for Langfuse tracing helpers."""

from core.tracing import is_tracing_enabled, trace_config, tracing_status


def test_trace_config_disabled_by_default():
    assert trace_config(run_id="run-1", agent_name="atlas") == {}


def test_tracing_status_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")

    from core.config import get_settings

    get_settings.cache_clear()

    status = tracing_status()
    assert status["enabled"] is is_tracing_enabled()
    assert status["configured"] is False
    assert status["dashboard_url"] is None
    assert status["reason"] == "disabled"

    get_settings.cache_clear()
