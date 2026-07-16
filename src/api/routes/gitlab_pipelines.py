from fastapi import APIRouter, HTTPException, Query

from api.schemas.requests import (
    PipelineJobItem,
    PipelineJobsResponse,
    PipelineListItem,
    PipelineListResponse,
    PlayPipelineJobRequest,
    PlayPipelineJobResponse,
)
from api.services.gitlab_pipeline_service import GitLabPipelineService

router = APIRouter(prefix="/api/v1/gitlab", tags=["gitlab"])

_service: GitLabPipelineService | None = None


def _get_service() -> GitLabPipelineService:
    global _service
    if _service is None:
        _service = GitLabPipelineService()
    return _service


@router.get("/pipelines", response_model=PipelineListResponse)
async def list_pipelines(
    ref: str | None = Query(default=None),
    status: str | None = Query(default=None, description="running, pending, success, failed, manual, ..."),
    limit: int = Query(default=30, ge=1, le=100),
):
    try:
        pipelines = await _get_service().list_pipelines(ref=ref, status=status, limit=limit)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return PipelineListResponse(
        count=len(pipelines),
        pipelines=[PipelineListItem(**p) for p in pipelines],
    )


@router.get("/pipelines/{pipeline_id}/jobs", response_model=PipelineJobsResponse)
async def list_pipeline_jobs(pipeline_id: int):
    try:
        jobs = await _get_service().list_jobs(pipeline_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return PipelineJobsResponse(
        pipeline_id=pipeline_id,
        count=len(jobs),
        jobs=[PipelineJobItem(**j) for j in jobs],
    )


@router.post("/jobs/{job_id}/play", response_model=PlayPipelineJobResponse)
async def play_pipeline_job(job_id: int, request: PlayPipelineJobRequest | None = None):
    """
    Run a manual GitLab CI job (typically bump-version after a feat: commit).

    Standard variable: ENV=dev|stg|prd — triggers version bump and downstream CI;
    then sync the new version in Argo CD for the target environment.
    """
    req = request or PlayPipelineJobRequest()
    try:
        result = await _get_service().play_job(
            job_id=job_id,
            variables=[v.model_dump() for v in req.variables],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return PlayPipelineJobResponse(**result)


@router.post("/jobs/{job_id}/retry", response_model=PlayPipelineJobResponse)
async def retry_pipeline_job(job_id: int, request: PlayPipelineJobRequest | None = None):
    """
    Retry a GitLab CI job that has already run (success, failed, canceled, skipped).

    For manual jobs still waiting, use POST /jobs/{job_id}/play instead.
    Optional variables (e.g. ENV for bump-version) can be supplied on retry.
    """
    req = request or PlayPipelineJobRequest(variables=[])
    try:
        result = await _get_service().retry_job(
            job_id=job_id,
            variables=[v.model_dump() for v in req.variables],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return PlayPipelineJobResponse(**result)
