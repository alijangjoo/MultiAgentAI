"""REST API for Deploy Request dashboard."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.schemas.requests import (
    AssignDeployJiraRequest,
    DeployRequestResponse,
    UpdateDeployRequestRequest,
)
from core.config import get_settings
from slices.deploy_request.models.state import DeployRequest
from slices.deploy_request.orchestrator import DeployRequestOrchestrator
from slices.deploy_request.poller import poll_deploy_requests_once
from slices.deploy_request.repository import DeployRequestRepository

router = APIRouter(prefix="/api/v1/deploy-requests", tags=["deploy-requests"])


class TriggerStageMrRequest(BaseModel):
    mr_iid: int = Field(..., ge=1, examples=[940])


class StagePipelineListItem(BaseModel):
    pipeline_id: int
    tag: str
    version: str | None = None
    status: str
    sha: str | None = None
    web_url: str | None = None
    created_at: str | None = None
    source_branch: str | None = None
    jira_key: str | None = None
    mr_iid: int | None = None
    mr_url: str | None = None
    deploy_request_id: str | None = None
    deploy_status: str | None = None
    jobs_complete: bool = False
    selectable: bool = False


class SendToMattermostRequest(BaseModel):
    priority: str | None = Field(default=None, examples=["P1"])
    publish_at: str | None = Field(default=None, examples=["2026-07-12 14:00"])
    message_body: str | None = None
    version: str | None = None
    jira_key: str | None = None
    resolved_by: str = Field(default="tech-lead@dashboard")


def _get_orchestrator() -> DeployRequestOrchestrator:
    return DeployRequestOrchestrator()


def _get_repo() -> DeployRequestRepository:
    return DeployRequestRepository()


def _to_response(req: DeployRequest) -> DeployRequestResponse:
    return DeployRequestResponse(**req.model_dump())


@router.get("", response_model=list[DeployRequestResponse])
async def list_deploy_requests(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    items = await _get_repo().list(status=status, limit=limit)
    return [_to_response(i) for i in items]


@router.get("/open-mrs")
async def list_open_mrs(limit: int = Query(default=30, ge=1, le=100)):
    """Open MRs targeting Dev / Stage / Production (Stage has Prepare button)."""
    return await _get_orchestrator().list_open_mrs_by_environment(limit=limit)


@router.post("/sync")
async def sync_from_gitlab():
    """Poll GitLab for successful Stage pipelines (localhost cannot receive webhooks)."""
    result = await poll_deploy_requests_once()
    settings = get_settings()
    return {
        **result,
        "poll_enabled": settings.deploy_poll_enabled,
        "poll_interval_seconds": settings.deploy_poll_interval_seconds,
        "message": (
            f"Synced successful Stage tag pipelines (*-stg): "
            f"scanned={result.get('pipelines_checked')}/{result.get('scan_limit')}, "
            f"created={result.get('created')}, "
            f"skipped_history={result.get('skipped_history')}, "
            f"ready_limit={result.get('ready_limit')}"
        ),
    }


@router.post("/trigger-stage-mr")
async def trigger_stage_mr(body: TriggerStageMrRequest):
    """
    Manual Prepare on a Stage MR:
    - not merged → ask user to merge in GitLab
    - merged → start Deploy Request (idempotent history by mr_iid)
    """
    try:
        return await _get_orchestrator().trigger_from_stage_mr(body.mr_iid)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stage-pipelines", response_model=list[StagePipelineListItem])
async def list_stage_pipelines(
    limit: int = Query(default=30, ge=1, le=100),
):
    """Stage release-tag pipelines from GitLab (tag + merged branch / Jira preview)."""
    try:
        items = await _get_orchestrator().list_stage_pipelines_for_dashboard(limit=limit)
        return [StagePipelineListItem(**i) for i in items]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/from-pipeline/{pipeline_id}", response_model=DeployRequestResponse)
async def open_from_pipeline(pipeline_id: int):
    """Select a Stage tag pipeline → register Deploy Request and resolve MR / branch."""
    try:
        req = await _get_orchestrator().open_stage_pipeline(pipeline_id)
        return _to_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{request_id}", response_model=DeployRequestResponse)
async def get_deploy_request(request_id: str):
    req = await _get_repo().get(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Deploy request not found")
    return _to_response(req)


@router.patch("/{request_id}", response_model=DeployRequestResponse)
async def update_deploy_request(request_id: str, body: UpdateDeployRequestRequest):
    try:
        req = await _get_orchestrator().update_draft(
            request_id,
            priority=body.priority,
            publish_at=body.publish_at,
            message_body=body.message_body,
            version=body.version,
            jira_key=body.jira_key,
        )
        return _to_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{request_id}/assign-jira", response_model=DeployRequestResponse)
async def assign_jira(request_id: str, body: AssignDeployJiraRequest):
    try:
        req = await _get_orchestrator().assign_jira(request_id, body.jira_key)
        return _to_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{request_id}/generate-message", response_model=DeployRequestResponse)
async def generate_message(request_id: str):
    """Generate Deploy Request message from a successful Stage pipeline (dashboard click)."""
    try:
        req = await _get_orchestrator().generate_message(request_id)
        return _to_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{request_id}/send-to-mattermost", response_model=DeployRequestResponse)
async def send_to_mattermost(request_id: str, body: SendToMattermostRequest | None = None):
    """Send prepared Deploy Request message to Mattermost webhook."""
    payload = body or SendToMattermostRequest()
    try:
        req = await _get_orchestrator().send_to_mattermost(
            request_id,
            resolved_by=payload.resolved_by,
            priority=payload.priority,
            publish_at=payload.publish_at,
            message_body=payload.message_body,
            version=payload.version,
            jira_key=payload.jira_key,
        )
        return _to_response(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
