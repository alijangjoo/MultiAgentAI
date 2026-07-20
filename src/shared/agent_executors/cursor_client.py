"""HTTP client for the local Cursor Bridge (git-aware develop/review on Windows clone)."""

from typing import Any

import httpx

from core.config import get_settings


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
    mr_title: str,
    prompt: str,
    mr_changes: list[dict] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.cursor_bridge_url.rstrip('/')}/review"
    payload = {
        "run_id": run_id,
        "task_key": task_key,
        "branch_name": branch_name,
        "mr_title": mr_title,
        "prompt": prompt,
        "mr_changes": mr_changes or [],
        "repo_path": settings.cursor_repo_path,
        "model": settings.code_review_model or settings.cursor_model,
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
            raise CursorBridgeError(f"Cursor Bridge review failed: {detail}")
        return response.json()
