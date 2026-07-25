"""LLM tracing via Langfuse — individual traces, sessions, and cost dashboards."""

from __future__ import annotations

import time
from typing import Any

from core.config import get_settings

_handler: Any | None = None
_langfuse_client: Any | None = None

_PLACEHOLDER_KEYS = frozenset({"pk-lf-...", "sk-lf-..."})


def _has_valid_langfuse_keys(public_key: str, secret_key: str) -> bool:
    if not public_key or not secret_key:
        return False
    if public_key in _PLACEHOLDER_KEYS or secret_key in _PLACEHOLDER_KEYS:
        return False
    if public_key == secret_key:
        return False
    return public_key.startswith("pk-lf-") and secret_key.startswith("sk-lf-")


def _langfuse_config_issue(settings: Any) -> str | None:
    if not settings.langfuse_enabled:
        return "disabled"
    public_key = settings.langfuse_public_key
    secret_key = settings.langfuse_secret_key
    if not public_key or not secret_key:
        return "missing_keys"
    if public_key in _PLACEHOLDER_KEYS or secret_key in _PLACEHOLDER_KEYS:
        return "placeholder_keys"
    if "paste" in public_key.lower() or "paste" in secret_key.lower():
        return "placeholder_keys"
    if public_key == secret_key:
        return "duplicate_keys"
    if not public_key.startswith("pk-lf-"):
        return "invalid_public_key"
    if not secret_key.startswith("sk-lf-"):
        return "invalid_secret_key"
    return None


def init_tracing() -> None:
    """Initialize Langfuse when tracing is enabled. Call once at startup."""
    global _handler, _langfuse_client
    settings = get_settings()
    if _langfuse_config_issue(settings) is not None:
        return

    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    _langfuse_client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    # Langfuse SDK v4: credentials live on the client; handler reads via get_client().
    _handler = CallbackHandler()


def is_tracing_enabled() -> bool:
    return _handler is not None


def get_callback_handler() -> Any | None:
    return _handler


def trace_config(
    *,
    run_id: str | None = None,
    agent_name: str | None = None,
    workflow_type: str | None = None,
    tags: list[str] | None = None,
    **extra_metadata: Any,
) -> dict[str, Any]:
    """Build RunnableConfig for LangGraph / LangChain with Langfuse metadata."""
    if not is_tracing_enabled():
        return {}

    metadata: dict[str, Any] = dict(extra_metadata)
    if run_id:
        metadata["langfuse_session_id"] = run_id
    if agent_name:
        metadata["agent_name"] = agent_name
    if workflow_type:
        metadata["workflow_type"] = workflow_type

    config: dict[str, Any] = {
        "callbacks": [_handler],
        "metadata": metadata,
    }
    if agent_name:
        config["run_name"] = agent_name
    if tags:
        config["tags"] = tags
    return config


def record_generation(
    *,
    run_id: str,
    name: str,
    model: str,
    prompt: str,
    output: str,
    latency_ms: float | None = None,
    tags: list[str] | None = None,
) -> None:
    """Record a non-LangChain LLM call (e.g. Cursor Bridge / 9Router)."""
    if not is_tracing_enabled() or _langfuse_client is None:
        return

    try:
        from langfuse import propagate_attributes

        metadata = {"latency_ms": latency_ms} if latency_ms is not None else None
        with propagate_attributes(session_id=run_id, tags=tags or []):
            with _langfuse_client.start_as_current_observation(
                as_type="generation",
                name=name,
                model=model,
                input=prompt,
                output=output,
                metadata=metadata,
            ):
                pass
    except Exception:
        pass


def flush_tracing() -> None:
    if _langfuse_client is not None:
        _langfuse_client.flush()


def tracing_status() -> dict[str, Any]:
    settings = get_settings()
    issue = _langfuse_config_issue(settings)
    configured = issue is None
    host = settings.langfuse_host.rstrip("/") if configured or settings.langfuse_enabled else None
    return {
        "enabled": is_tracing_enabled(),
        "configured": configured,
        "host": host,
        "dashboard_url": f"{host}/" if host and configured else None,
        "reason": issue,
    }


class GenerationTimer:
    """Context manager that records elapsed time for record_generation."""

    def __init__(self) -> None:
        self.started_at = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> GenerationTimer:
        self.started_at = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self.started_at) * 1000
