"""Normalize Mattermost outgoing webhooks and Grok Bot JSON into one alert."""

from __future__ import annotations

import hashlib
from typing import Any

from core.config import get_settings
from slices.channel_alerts.models import IncomingAlert


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def resolve_list(payload: dict[str, Any], settings: Any | None = None) -> str:
    """Map a webhook body to disaster or bugs."""
    cfg = settings or get_settings()
    explicit = _text(payload.get("list") or payload.get("channel_list")).lower()
    if explicit in {"disaster", "bugs", "bug"}:
        return "bugs" if explicit.startswith("bug") else "disaster"

    channel_id = _text(payload.get("channel_id"))
    bugs_id = _text(getattr(cfg, "mattermost_bugs_channel_id", ""))
    disaster_id = _text(getattr(cfg, "mattermost_disaster_channel_id", ""))
    if bugs_id and channel_id == bugs_id:
        return "bugs"
    if disaster_id and channel_id == disaster_id:
        return "disaster"

    name = _text(
        payload.get("channel_name") or payload.get("channel") or payload.get("channel_display_name")
    ).lower()
    bugs_name = _text(getattr(cfg, "mattermost_bugs_channel_name", "bugs")).lower()
    disaster_name = _text(getattr(cfg, "mattermost_disaster_channel_name", "disaster")).lower()
    if bugs_name and bugs_name in name:
        return "bugs"
    if "bug" in name:
        return "bugs"
    if disaster_name and disaster_name in name:
        return "disaster"
    if "disaster" in name:
        return "disaster"
    raise ValueError(
        "Cannot tell Disaster from Bugs. Send list=disaster or list=bugs, or match the channel name/id."
    )


def external_id(payload: dict[str, Any], text: str) -> str:
    for key in ("post_id", "message_id", "id"):
        value = _text(payload.get(key))
        if value:
            return value[:128]
    basis = "|".join(
        [
            _text(payload.get("channel_id")),
            _text(payload.get("user_name") or payload.get("user_id")),
            _text(payload.get("timestamp") or payload.get("create_at")),
            text,
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def normalize_payload(payload: dict[str, Any], settings: Any | None = None) -> IncomingAlert:
    text = _text(payload.get("text") or payload.get("message"))
    if not text:
        raise ValueError("Message text is empty")
    return IncomingAlert(
        external_id=external_id(payload, text),
        list_name=resolve_list(payload, settings),
        channel_id=_text(payload.get("channel_id")),
        channel_name=_text(payload.get("channel_name") or payload.get("channel")),
        user_name=_text(payload.get("user_name") or payload.get("username") or payload.get("user_id")),
        text=text,
    )