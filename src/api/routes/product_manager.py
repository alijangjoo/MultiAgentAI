from fastapi import APIRouter, HTTPException

from api.schemas.requests import (
    MeridianChatRequest,
    MeridianChatResponse,
    MeridianCreateJiraRequest,
    MeridianCreateJiraResponse,
    MeridianGeneratePRDRequest,
    MeridianGeneratePRDResponse,
)
from core.config import get_settings
from slices.product_manager.orchestrator import ProductManagerOrchestrator

router = APIRouter(prefix="/api/v1/product-manager", tags=["product-manager"])

_orchestrator: ProductManagerOrchestrator | None = None


def _get_orchestrator() -> ProductManagerOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ProductManagerOrchestrator()
    return _orchestrator


@router.post("/chat", response_model=MeridianChatResponse)
async def meridian_chat(request: MeridianChatRequest):
    try:
        result = await _get_orchestrator().chat(
            session_id=request.session_id,
            message=request.message,
            role=request.role,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MeridianChatResponse(**result.model_dump())


@router.post("/prd", response_model=MeridianGeneratePRDResponse)
async def generate_prd(request: MeridianGeneratePRDRequest):
    try:
        result = await _get_orchestrator().generate_prd(
            session_id=request.session_id,
            title=request.title,
            stakeholders=request.stakeholders,
            tech_lead=request.tech_lead,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MeridianGeneratePRDResponse(
        session_id=result.session_id,
        run_id=result.run_id,
        prd_content=result.prd_content,
        message=f"PRD generated: {result.title}",
    )


@router.post("/jira/create", response_model=MeridianCreateJiraResponse)
async def create_jira_from_prd(request: MeridianCreateJiraRequest):
    settings = get_settings()
    try:
        result = await _get_orchestrator().create_jira_task(
            session_id=request.session_id,
            summary=request.summary,
            prd_content=request.prd_content,
            issue_type=request.issue_type,
            labels=request.labels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    jira_url = f"{settings.jira_url.rstrip('/')}/browse/{result.jira_key}" if settings.jira_url else None
    return MeridianCreateJiraResponse(
        session_id=result.session_id,
        jira_key=result.jira_key,
        jira_url=jira_url,
        message=f"Jira issue {result.jira_key} created",
    )
