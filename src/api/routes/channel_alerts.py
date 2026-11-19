"""Webhook ingest and dashboard API for Disaster and Bugs channels."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.config import get_settings
from slices.channel_alerts.service import ChannelAlertService
from slices.channel_alerts.settings_store import (
    OLLAMA_MODELS,
    get_channel_alert_settings,
    save_channel_alert_settings,
)

router = APIRouter(prefix="/api/v1/channel-alerts", tags=["channel-alerts"])


class ClassifierUpdate(BaseModel):
    classifier: str = Field(description="ollama or cursor_cli")
    ollama_model: str = "llama3.2:3b"


class ManualVendorReview(BaseModel):
    vendor_related: bool
    vendor_name: str = ""
    reason: str = ""


def _service() -> ChannelAlertService:
    return ChannelAlertService()


def _verify_token(token: str | None) -> None:
    expected = (get_settings().channel_alert_webhook_secret or "").strip()
    if not expected:
        return
    provided = (token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid channel alert webhook token")


async def _body_as_dict(request: Request) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="JSON body must be an object")
        return data
    form = await request.form()
    return {key: value for key, value in form.items()}


@router.post("/webhook")
async def ingest_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_channel_alert_token: str | None = Header(default=None, alias="X-Channel-Alert-Token"),
):
    """Accept a Mattermost outgoing webhook or a Grok Bot automation POST."""
    payload = await _body_as_dict(request)
    token = x_channel_alert_token or str(payload.get("token") or payload.get("webhook_secret") or "")
    _verify_token(token)
    try:
        saved = await _service().accept(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if saved.classification_status != "done":
        background_tasks.add_task(_service().classify_saved, saved.id)
    return {"ok": True, "alert": saved.model_dump()}


@router.get("")
async def list_channel_alerts(
    kind: str = Query(default="disaster", description="disaster, bugs, or vendor"),
    limit: int = Query(default=100, ge=1, le=300),
):
    try:
        items = await _service().list_alerts(kind, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"kind": kind, "items": [item.model_dump() for item in items]}


@router.get("/settings")
async def read_settings():
    current = get_channel_alert_settings()
    return {
        "classifier": current.classifier,
        "ollama_model": current.ollama_model,
        "ollama_models": list(OLLAMA_MODELS),
        "webhook_path": "/api/v1/channel-alerts/webhook",
    }


@router.post("/recheck")
async def recheck_open_alerts(background_tasks: BackgroundTasks):
    """Queue a fresh vendor classification for messages that are not on the vendor list."""
    service = _service()
    ids = await service.open_ids()
    queued: list[str] = []
    for alert_id in ids:
        prepared = await service.prepare_recheck(alert_id)
        if prepared is None:
            continue
        background_tasks.add_task(service.classify_saved, alert_id)
        queued.append(alert_id)
    return {"queued": len(queued)}


@router.post("/{alert_id}/recheck")
async def recheck_alert(alert_id: str, background_tasks: BackgroundTasks):
    service = _service()
    prepared = await service.prepare_recheck(alert_id)
    if prepared is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    background_tasks.add_task(service.classify_saved, alert_id)
    return {"ok": True, "alert": prepared.model_dump()}


@router.post("/{alert_id}/manual")
async def manual_vendor_review(alert_id: str, body: ManualVendorReview):
    saved = await _service().manual_review(
        alert_id,
        vendor_related=body.vendor_related,
        vendor_name=body.vendor_name,
        reason=body.reason,
    )
    if saved is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True, "alert": saved.model_dump()}


@router.put("/settings")
async def update_settings(body: ClassifierUpdate):
    try:
        saved = save_channel_alert_settings(body.classifier, body.ollama_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "classifier": saved.classifier,
        "ollama_model": saved.ollama_model,
        "ollama_models": list(OLLAMA_MODELS),
    }