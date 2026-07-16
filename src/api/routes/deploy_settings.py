from fastapi import APIRouter, HTTPException, Query

from api.schemas.requests import DeployBranchSettingsResponse, UpdateDeployBranchSettingsRequest
from shared.deploy_settings.store import (
    DeployBranchSettings,
    get_deploy_branch_settings,
    save_deploy_branch_settings,
)
from shared.integrations.registry import get_integrations
from shared.utils.gitlab_branches import normalize_branch_list

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/deploy-branches", response_model=DeployBranchSettingsResponse)
async def get_deploy_branch_config():
    cfg = get_deploy_branch_settings()
    return DeployBranchSettingsResponse(**cfg.model_dump())


@router.put("/deploy-branches", response_model=DeployBranchSettingsResponse)
async def update_deploy_branch_config(request: UpdateDeployBranchSettingsRequest):
    saved = save_deploy_branch_settings(
        DeployBranchSettings(
            dev_target_branch=request.dev_target_branch,
            stage_target_branch=request.stage_target_branch,
            production_target_branch=request.production_target_branch,
            feature_source_branch=request.feature_source_branch,
            is_automatic_send_message=request.is_automatic_send_message,
            updated_by=request.updated_by,
        )
    )
    return DeployBranchSettingsResponse(**saved.model_dump())


@router.get("/gitlab-branches")
async def list_gitlab_branches(
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    gitlab = get_integrations().gitlab
    if not hasattr(gitlab, "list_branches"):
        raise HTTPException(status_code=501, detail="GitLab branch listing not available")
    try:
        remote = await gitlab.list_branches(search=search, limit=limit)
        branches = normalize_branch_list(remote, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"branches": branches, "count": len(branches)}
