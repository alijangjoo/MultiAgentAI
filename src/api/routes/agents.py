from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas.requests import (
    AgentEventResponse,
    AgentRunResponse,
    DashboardStatsResponse,
    FeaturePipelineRequest,
    FeaturePipelineResponse,
    HITLResolveRequest,
    HITLResolveResponse,
    IncidentAnalysisRequest,
    IncidentAnalysisResponse,
    IncidentCreatePRDRequest,
    IncidentCreatePRDResponse,
)
from shared.models.domain import HITLAction, RunStatus
from shared.persistence.repository import AgentRunRepository, HITLRepository
from slices.feature_pipeline.models.state import FeaturePipelineInput
from slices.feature_pipeline.orchestrator import FeaturePipelineOrchestrator
from slices.incident_response.models.state import IncidentAnalysisInput
from slices.incident_response.orchestrator import IncidentResponseOrchestrator
from slices.product_manager.orchestrator import ProductManagerOrchestrator

router = APIRouter(prefix="/api/v1", tags=["agents"])

_run_repo = AgentRunRepository()
_hitl_repo = HITLRepository()
_feature_orchestrator: FeaturePipelineOrchestrator | None = None
_incident_orchestrator: IncidentResponseOrchestrator | None = None
_pm_orchestrator: ProductManagerOrchestrator | None = None


def _get_feature_orchestrator() -> FeaturePipelineOrchestrator:
    global _feature_orchestrator
    if _feature_orchestrator is None:
        _feature_orchestrator = FeaturePipelineOrchestrator()
    return _feature_orchestrator


def _get_incident_orchestrator() -> IncidentResponseOrchestrator:
    global _incident_orchestrator
    if _incident_orchestrator is None:
        _incident_orchestrator = IncidentResponseOrchestrator()
    return _incident_orchestrator


def _get_pm_orchestrator() -> ProductManagerOrchestrator:
    global _pm_orchestrator
    if _pm_orchestrator is None:
        _pm_orchestrator = ProductManagerOrchestrator()
    return _pm_orchestrator


@router.post("/workflows/feature-development", response_model=FeaturePipelineResponse)
async def start_feature_development(
    request: FeaturePipelineRequest,
    background_tasks: BackgroundTasks,
):
    """Scenario 1: Start the full feature development pipeline (Atlas -> Forge -> Sentinel -> HITL)."""
    input_data = FeaturePipelineInput(**request.model_dump())

    try:
        state = await _get_feature_orchestrator().start_pipeline(input_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    mr_url = None
    if state.sentinel_output and state.sentinel_output.merge_request:
        mr_url = state.sentinel_output.merge_request.url

    return FeaturePipelineResponse(
        run_id=state.run_id,
        status=state.status,
        task_key=state.task_key,
        hitl_checkpoint_id=state.hitl_checkpoint_id,
        merge_request_url=mr_url,
        message=(
            "Pipeline paused at HITL checkpoint. "
            "Review the MR and approve merge via POST /api/v1/hitl/{checkpoint_id}/resolve"
        ),
    )


@router.post("/workflows/incident-analysis", response_model=IncidentAnalysisResponse)
async def start_incident_analysis(request: IncidentAnalysisRequest):
    """Scenario 2: Analyze Disaster channel messages and generate incident report."""
    input_data = IncidentAnalysisInput(**request.model_dump())

    try:
        run_id, output = await _get_incident_orchestrator().analyze_disaster_channel(input_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return IncidentAnalysisResponse(
        run_id=run_id,
        status="completed",
        report=output.report.model_dump(),
        message=f"Incident report generated for Tech Lead: {output.report.title}",
    )


@router.post("/workflows/incident-analysis/{run_id}/create-prd", response_model=IncidentCreatePRDResponse)
async def create_prd_from_incident(run_id: str, request: IncidentCreatePRDRequest):
    """Dashboard command: send vendor-related incident to Meridian for PRD generation."""
    run = await _run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Incident run not found")

    output = run.get("output_payload") or {}
    report = output.get("report")
    if not report and output.get("severity"):
        report = output

    if not report:
        raise HTTPException(status_code=400, detail="No incident report found in run output")

    if not report.get("is_vendor_related", False):
        raise HTTPException(
            status_code=400,
            detail="Incident is not vendor-related. No PRD workflow started.",
        )

    try:
        session_id, prd_run_id = await _get_pm_orchestrator().start_from_incident(
            incident_report=report,
            tech_lead=request.tech_lead,
            session_id=request.session_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return IncidentCreatePRDResponse(
        run_id=run_id,
        session_id=session_id,
        prd_run_id=prd_run_id,
        message="Meridian PRD generated from incident. Create Jira task via Product Manager panel.",
    )


@router.get("/runs", response_model=list[AgentRunResponse])
async def list_runs(
    workflow_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    run_status = RunStatus(status) if status else None
    runs = await _run_repo.list_runs(
        workflow_type=workflow_type,
        status=run_status,
        limit=limit,
    )
    return [AgentRunResponse(**run) for run in runs]


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_run(run_id: str):
    run = await _run_repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return AgentRunResponse(**run)


@router.get("/runs/{run_id}/events", response_model=list[AgentEventResponse])
async def get_run_events(run_id: str):
    events = await _run_repo.get_events(run_id)
    return [AgentEventResponse(**event) for event in events]


@router.post("/hitl/{checkpoint_id}/resolve", response_model=HITLResolveResponse)
async def resolve_hitl_checkpoint(checkpoint_id: str, request: HITLResolveRequest):
    """Human-in-the-loop: approve merge (feature) or publish Deploy Request."""
    checkpoint = await _hitl_repo.get_checkpoint(checkpoint_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    if checkpoint.resolved:
        raise HTTPException(status_code=400, detail="Checkpoint already resolved")

    is_deploy = checkpoint.checkpoint_name == "deploy_request_approval"
    is_mr_review = checkpoint.checkpoint_name == "mr_review_approval"

    # MR review approve: merge first so a failed merge leaves the checkpoint pending for retry.
    if request.action == HITLAction.APPROVE and is_mr_review:
        try:
            from api.services.gitlab_mr_service import GitLabMRService

            mr_iid = int(checkpoint.context.get("mr_iid") or 0)
            if not mr_iid:
                raise ValueError("HITL checkpoint missing mr_iid")
            merge_result = await GitLabMRService().merge_after_hitl(
                run_id=checkpoint.run_id,
                mr_iid=mr_iid,
                merged_by=request.resolved_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        await _hitl_repo.resolve_checkpoint(
            checkpoint_id=checkpoint_id,
            action=request.action,
            resolved_by=request.resolved_by,
        )
        await _run_repo.update_run(
            checkpoint.run_id,
            status=RunStatus.COMPLETED,
            output_payload={
                **(checkpoint.context or {}),
                "merged": True,
                "merge_result": merge_result,
            },
        )
        return HITLResolveResponse(
            checkpoint_id=checkpoint_id,
            run_id=checkpoint.run_id,
            action=request.action,
            pipeline_status="merged",
            message=merge_result.get("message", "MR merged"),
        )

    await _hitl_repo.resolve_checkpoint(
        checkpoint_id=checkpoint_id,
        action=request.action,
        resolved_by=request.resolved_by,
    )

    if request.action == HITLAction.APPROVE:
        try:
            if is_deploy:
                from slices.deploy_request.orchestrator import DeployRequestOrchestrator

                deploy_req = await DeployRequestOrchestrator().publish_after_approval(
                    run_id=checkpoint.run_id,
                    resolved_by=request.resolved_by,
                )
                return HITLResolveResponse(
                    checkpoint_id=checkpoint_id,
                    run_id=checkpoint.run_id,
                    action=request.action,
                    pipeline_status=deploy_req.status.value,
                    message="Deploy Request approved and published to Mattermost.",
                )

            state = await _get_feature_orchestrator().complete_after_merge(
                run_id=checkpoint.run_id,
                merged_by=request.resolved_by,
            )
            return HITLResolveResponse(
                checkpoint_id=checkpoint_id,
                run_id=checkpoint.run_id,
                action=request.action,
                pipeline_status=state.status,
                message="Merge approved. Confluence documentation updated by Scribe agent.",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if is_deploy:
        from slices.deploy_request.orchestrator import DeployRequestOrchestrator

        await DeployRequestOrchestrator().reject(
            run_id=checkpoint.run_id,
            resolved_by=request.resolved_by,
        )
        return HITLResolveResponse(
            checkpoint_id=checkpoint_id,
            run_id=checkpoint.run_id,
            action=request.action,
            pipeline_status="cancelled",
            message=f"Deploy Request {request.action.value}.",
        )

    if is_mr_review:
        await _run_repo.update_run(checkpoint.run_id, status=RunStatus.COMPLETED)
        return HITLResolveResponse(
            checkpoint_id=checkpoint_id,
            run_id=checkpoint.run_id,
            action=request.action,
            pipeline_status="review_pending",
            message=(
                "Developer should fix findings and click Review again."
                if request.action == HITLAction.REQUEST_CHANGES
                else f"MR review {request.action.value}."
            ),
        )

    await _run_repo.update_run(checkpoint.run_id, status=RunStatus.CANCELLED)
    return HITLResolveResponse(
        checkpoint_id=checkpoint_id,
        run_id=checkpoint.run_id,
        action=request.action,
        pipeline_status="cancelled",
        message=f"Merge {request.action.value}. Pipeline cancelled.",
    )


@router.get("/hitl/pending")
async def list_pending_hitl():
    checkpoints = await _hitl_repo.get_pending_checkpoints()
    return [
        {
            "id": cp.id,
            "run_id": cp.run_id,
            "checkpoint_name": cp.checkpoint_name,
            "description": cp.description,
            "context": cp.context,
            "created_at": cp.created_at.isoformat(),
        }
        for cp in checkpoints
    ]


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats():
    all_runs = await _run_repo.list_runs(limit=1000)
    pending_hitl = await _hitl_repo.get_pending_checkpoints()

    return DashboardStatsResponse(
        total_runs=len(all_runs),
        running=sum(1 for r in all_runs if r["status"] == RunStatus.RUNNING.value),
        waiting_hitl=sum(1 for r in all_runs if r["status"] == RunStatus.WAITING_HITL.value),
        completed=sum(1 for r in all_runs if r["status"] == RunStatus.COMPLETED.value),
        failed=sum(1 for r in all_runs if r["status"] == RunStatus.FAILED.value),
        pending_hitl_checkpoints=len(pending_hitl),
    )
