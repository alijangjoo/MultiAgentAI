"""HTTP client for the local Cursor Bridge (git-aware develop/review on Windows clone)."""

import json
from typing import Any

import httpx

from core.config import get_settings
from shared.cursor_cli.model_utils import normalize_cursor_cli_model


class CursorBridgeError(Exception):
    pass


def _parse_bridge_error(response: httpx.Response) -> str:
    """Extract a human-readable message from Bridge/FastAPI error bodies."""
    text = (response.text or "").strip()
    if not text:
        return f"HTTP {response.status_code}"
    try:
        data = response.json()
        if isinstance(data, dict):
            detail = data.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            if detail is not None:
                return str(detail)
    except json.JSONDecodeError:
        pass
    if text.startswith("{") and '"detail"' in text:
        try:
            detail = json.loads(text).get("detail")
            if isinstance(detail, str):
                return detail
        except json.JSONDecodeError:
            pass
    return text[:500]


async def cursor_bridge_develop(
    *,
    task_key: str,
    branch_name: str,
    prompt: str,
    run_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.cursor_bridge_url.rstrip('/')}/develop"
    payload = {
        "run_id": run_id,
        "task_key": task_key,
        "branch_name": branch_name,
        "prompt": prompt,
        "repo_path": settings.cursor_repo_path,
        "model": settings.cursor_model,
    }
    async with httpx.AsyncClient(timeout=600.0) as client:
        try:
            response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise CursorBridgeError(
                f"Cursor Bridge not reachable at {settings.cursor_bridge_url}. "
                "Start it with: python run_cursor_bridge.py"
            ) from exc
        if response.status_code >= 400:
            raise CursorBridgeError(f"Cursor Bridge develop failed: {_parse_bridge_error(response)}")
        return response.json()


def _review_subprocess_timeout(settings, timeout_seconds: int | None = None) -> int:
    return (
        timeout_seconds
        or settings.cursor_cli_review_timeout_seconds
        or settings.cursor_cli_timeout_seconds
    )


async def cursor_bridge_review(
    *,
    run_id: str,
    task_key: str,
    branch_name: str,
    context: dict[str, Any],
    model: str | None = None,
    workspace: str | None = None,
    output_format: str | None = None,
    mode: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.cursor_bridge_url.rstrip('/')}/review"
    review_timeout = _review_subprocess_timeout(settings, timeout_seconds)
    payload = {
        "run_id": run_id,
        "task_key": task_key,
        "branch_name": branch_name,
        "repo_path": settings.cursor_repo_path,
        "context": context,
        "model": normalize_cursor_cli_model(
            model or settings.cursor_model or settings.code_review_model
        ),
        "output_format": output_format or settings.cursor_cli_review_output_format,
        "mode": mode or settings.cursor_cli_review_mode or settings.cursor_cli_mode,
        "timeout_seconds": review_timeout,
    }
    if workspace:
        payload["workspace"] = workspace
    # Bridge may retry CLI (ask → agent, multiple models); allow headroom beyond one subprocess.
    httpx_timeout = float(review_timeout) * 4 + 120.0
    async with httpx.AsyncClient(timeout=httpx_timeout) as client:
        try:
            response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise CursorBridgeError(
                f"Cursor Bridge not reachable at {settings.cursor_bridge_url}. "
                "Start it with: python run_cursor_bridge.py"
            ) from exc
        if response.status_code >= 400:
            raise CursorBridgeError(_parse_bridge_error(response))
        return response.json()


async def cursor_bridge_qa(
    *,
    run_id: str,
    task_key: str,
    branch_name: str,
    context: dict[str, Any],
    model: str | None = None,
    timeout_seconds: int | None = None,
    repo_path: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.cursor_bridge_url.rstrip('/')}/qa"
    review_timeout = _review_subprocess_timeout(settings, timeout_seconds)
    resolved_repo = (repo_path or settings.cursor_repo_path or "").strip()
    payload = {
        "run_id": run_id,
        "task_key": task_key,
        "branch_name": branch_name,
        "repo_path": resolved_repo,
        "context": context,
        "model": normalize_cursor_cli_model(
            model or settings.cursor_model or settings.code_review_model
        ),
        "output_format": "json",
        "mode": settings.cursor_cli_review_mode or settings.cursor_cli_mode,
        "timeout_seconds": review_timeout,
    }
    httpx_timeout = float(review_timeout) * 4 + 120.0
    async with httpx.AsyncClient(timeout=httpx_timeout) as client:
        try:
            response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise CursorBridgeError(
                f"Cursor Bridge not reachable at {settings.cursor_bridge_url}. "
                "Start it with: python run_cursor_bridge.py"
            ) from exc
        if response.status_code >= 400:
            raise CursorBridgeError(_parse_bridge_error(response))
        return response.json()
