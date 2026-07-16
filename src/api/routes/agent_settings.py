from fastapi import APIRouter, HTTPException

from api.schemas.requests import AgentExecutorSettingsResponse, UpdateAgentExecutorSettingsRequest
from core.config import get_settings
from shared.agent_executors.models import EXECUTOR_LABELS, AgentExecutorType
from shared.agent_executors.settings_store import (
    get_agent_executor_settings,
    save_agent_executor_settings,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/agent-executors", response_model=AgentExecutorSettingsResponse)
async def get_executor_settings():
    settings = get_agent_executor_settings()
    env = get_settings()
    return AgentExecutorSettingsResponse(
        forge_executor=settings.forge_executor.value,
        sentinel_executor=settings.sentinel_executor.value,
        updated_at=settings.updated_at,
        updated_by=settings.updated_by,
        options=[
            {"id": key, "label": label}
            for key, label in EXECUTOR_LABELS.items()
        ],
        cursor_repo_path=env.cursor_repo_path,
        cursor_bridge_url=env.cursor_bridge_url,
        cursor_model=env.cursor_model,
    )


@router.put("/agent-executors", response_model=AgentExecutorSettingsResponse)
async def update_executor_settings(request: UpdateAgentExecutorSettingsRequest):
    try:
        forge = AgentExecutorType(request.forge_executor)
        sentinel = AgentExecutorType(request.sentinel_executor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid executor: {exc}") from exc

    saved = save_agent_executor_settings(
        forge_executor=forge,
        sentinel_executor=sentinel,
        updated_by=request.updated_by,
    )
    env = get_settings()
    return AgentExecutorSettingsResponse(
        forge_executor=saved.forge_executor.value,
        sentinel_executor=saved.sentinel_executor.value,
        updated_at=saved.updated_at,
        updated_by=saved.updated_by,
        options=[
            {"id": key, "label": label}
            for key, label in EXECUTOR_LABELS.items()
        ],
        cursor_repo_path=env.cursor_repo_path,
        cursor_bridge_url=env.cursor_bridge_url,
        cursor_model=env.cursor_model,
    )
