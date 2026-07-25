"""HTTP client for the local Cursor Bridge (git-aware develop/review on Windows clone)."""

from typing import Any

import httpx

from core.config import get_settings
from shared.cursor_cli.model_utils import normalize_cursor_cli_model


class CursorBridgeError(Exception):
    pass


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
            detail = response.text[:500]
            raise CursorBridgeError(f"Cursor Bridge develop failed: {detail}")
        return response.json()


async def cursor_bridge_review(
    *,
    run_id: str,
    task_key: str,
    branch_name: str,
    context: dict[str, Any],
    model: str | None = None,
    output_format: str | None = None,
    mode: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.cursor_bridge_url.rstrip('/')}/review"
    payload = {
        "run_id": run_id,
        "task_key": task_key,
        "branch_name": branch_name,
        "repo_path": settings.cursor_repo_path,
        "context": context,
        "model": normalize_cursor_cli_model(
            model or settings.cursor_model or settings.code_review_model
        ),
        "output_format": output_format or settings.cursor_cli_output_format,
        "mode": mode or settings.cursor_cli_review_mode or settings.cursor_cli_mode,
        "timeout_seconds": timeout_seconds or settings.cursor_cli_timeout_seconds,
    }
    timeout = float(timeout_seconds or settings.cursor_cli_timeout_seconds) + 60.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise CursorBridgeError(
                f"Cursor Bridge not reachable at {settings.cursor_bridge_url}. "
                "Start it with: python run_cursor_bridge.py"
            ) from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            raise CursorBridgeError(f"Cursor Bridge review failed: {detail}")
        return response.json()
