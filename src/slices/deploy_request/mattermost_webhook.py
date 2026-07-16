"""Post Deploy Request messages to a Mattermost incoming webhook."""

from __future__ import annotations

from typing import Any

import httpx

from core.config import get_settings


async def post_deploy_webhook(text: str, webhook_url: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    url = (webhook_url or settings.mattermost_deploy_webhook_url or "").strip()
    if not url:
        raise ValueError("MATTERMOST_DEPLOY_WEBHOOK_URL is not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json={"text": text})
        response.raise_for_status()
        body = response.text
        try:
            return response.json() if body else {"ok": True, "status_code": response.status_code}
        except Exception:
            return {"ok": True, "status_code": response.status_code, "body": body}
