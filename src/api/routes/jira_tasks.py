from fastapi import APIRouter, HTTPException, Query

from api.schemas.requests import (
    BranchPreviewResponse,
    CreateBranchRequest,
    CreateBranchResponse,
    DevelopResponse,
    FeaturePipelineResponse,
    JiraTaskDetailResponse,
    JiraTaskListResponse,
    StartDevelopmentRequest,
)
from api.services.jira_task_service import JiraTaskService
from slices.feature_pipeline.models.state import FeaturePipelineInput
from slices.feature_pipeline.orchestrator import FeaturePipelineOrchestrator

router = APIRouter(prefix="/api/v1/jira", tags=["jira-tasks"])

_task_service = JiraTaskService()
_orchestrator: FeaturePipelineOrchestrator | None = None


def _get_orchestrator() -> FeaturePipelineOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = FeaturePipelineOrchestrator()
    return _orchestrator


@router.get("/tasks", response_model=JiraTaskListResponse)
async def list_jira_tasks(
    project_key: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    try:
        result = await _task_service.list_tasks(
            project_key=project_key,
            max_results=limit,
            status=status,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Jira error: {exc}") from exc
    return JiraTaskListResponse(**result)


@router.get("/tasks/{issue_key}", response_model=JiraTaskDetailResponse)
async def get_jira_task_detail(issue_key: str):
    try:
        detail = await _task_service.get_task_detail(issue_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Jira error: {exc}") from exc
    return JiraTaskDetailResponse(**detail)


@router.get("/tasks/{issue_key}/branch/preview", response_model=BranchPreviewResponse)
async def preview_branch_name(
    issue_key: str,
    short_description: str = Query(..., min_length=1),
):
    try:
        detail = await _task_service.get_task_detail(issue_key)
        preview = _task_service.preview_branch_name(
            task_key=detail["key"],
            task_summary=detail["summary"],
            short_description=short_description,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BranchPreviewResponse(**preview)


@router.get("/tasks/{issue_key}/branch/suggest", response_model=BranchPreviewResponse)
async def suggest_branch_name(issue_key: str):
    """AI-generated short slug + branch name from task description."""
    try:
        result = await _task_service.suggest_branch_slug(issue_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return BranchPreviewResponse(**result)


@router.get("/source-branches")
async def list_source_branches(limit: int = Query(default=100, ge=1, le=200)):
    try:
        branches = await _task_service.list_source_branches(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return {"branches": branches}


@router.post("/tasks/{issue_key}/branch", response_model=CreateBranchResponse)
async def create_task_branch(issue_key: str, request: CreateBranchRequest):
    try:
        result = await _task_service.create_task_branch(
            issue_key=issue_key,
            short_description=request.short_description,
            source_branch=request.source_branch,
            branch_name=request.branch_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Branch creation failed: {exc}") from exc

    message = (
        f"Branch '{result['branch_name']}' created from '{result['source_branch']}'"
        if result.get("created")
        else f"Branch '{result['branch_name']}' already exists"
    )
    return CreateBranchResponse(**result, message=message)


@router.post("/tasks/{issue_key}/develop", response_model=DevelopResponse)
async def develop_task(issue_key: str, request: StartDevelopmentRequest):
    """Full develop workflow: branch from main → specs → forge → MR (LangGraph)."""
    input_data = FeaturePipelineInput(
        task_key=issue_key.upper(),
        branch_name=request.branch_name,
        short_description=request.short_description,
        environment=request.environment,
        source_branch=request.source_branch,
        target_branch=request.target_branch,
        create_mr=request.create_mr,
        subtask_index=request.subtask_index,
        tech_lead_email=request.tech_lead_email,
    )
    try:
        state = await _get_orchestrator().run_forge_only(input_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    forge = state.forge_output
    mr_url = forge.merge_request_url if forge else None
    return DevelopResponse(
        run_id=state.run_id,
        status=state.status,
        task_key=state.task_key,
        branch_name=forge.branch_name if forge else (request.branch_name or ""),
        files_changed=forge.files_changed if forge else [],
        development_summary=forge.development_summary if forge else "",
        merge_request_url=mr_url,
        merge_request_iid=forge.merge_request_iid if forge else None,
        target_branch=forge.target_branch if forge else request.target_branch,
        message=(
            f"Development completed on {forge.branch_name if forge else 'branch'}. "
            + (f"MR: {mr_url}" if mr_url else "No MR created.")
        ),
    )


@router.post("/tasks/{issue_key}/start-development", response_model=FeaturePipelineResponse)
async def start_development(issue_key: str, request: StartDevelopmentRequest):
    """Legacy alias for develop workflow."""
    develop_result = await develop_task(issue_key, request)
    return FeaturePipelineResponse(
        run_id=develop_result.run_id,
        status=develop_result.status,
        task_key=develop_result.task_key,
        hitl_checkpoint_id=None,
        merge_request_url=develop_result.merge_request_url,
        message=develop_result.message,
    )
