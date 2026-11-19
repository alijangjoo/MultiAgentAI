"""On-demand Navid report for the Vendor Jira board."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import get_settings
from shared.integrations.registry import get_integrations
from slices.jira_reporter.exceptions_store import add_exception, delete_exception, list_exceptions
from slices.jira_reporter.rules import build_report
from slices.jira_reporter.source import load_snapshot

router = APIRouter(prefix="/api/v1/jira-reporter", tags=["jira-reporter"])


class WipExceptionBody(BaseModel):
    person_id: str
    until: str
    reason: str = ""
    keys: list[str] = Field(default_factory=list)


@router.get("/report")
async def jira_reporter_report():
    settings = get_settings()
    try:
        snapshot = await load_snapshot(get_integrations().jira, settings.jira_project_key)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    exceptions = [item.model_dump() for item in list_exceptions()]
    return build_report(snapshot, exceptions)


@router.get("/exceptions")
async def read_exceptions():
    return {"items": [item.model_dump() for item in list_exceptions()]}


@router.post("/exceptions")
async def create_exception(body: WipExceptionBody):
    try:
        saved = add_exception(body.person_id, body.until, body.reason, body.keys)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return saved.model_dump()


@router.delete("/exceptions/{exception_id}")
async def remove_exception(exception_id: str):
    if not delete_exception(exception_id):
        raise HTTPException(status_code=404, detail="Exception not found")
    return {"ok": True}