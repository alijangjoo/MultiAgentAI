from fastapi import APIRouter, HTTPException, Query

from api.schemas.requests import (
    MergeRequestByEnvironmentResponse,
    MergeRequestListItem,
    MergeRequestListResponse,
    MergeRequestMergeRequest,
    MergeRequestMergeResponse,
    MergeRequestLastReviewResponse,
    MergeRequestReviewContextResponse,
    MergeRequestReviewRequest,
    MergeRequestReviewResponse,
    MergeRequestStatusResponse,
)
from api.services.gitlab_mr_service import GitLabMRService

router = APIRouter(prefix="/api/v1/gitlab", tags=["gitlab"])

_service: GitLabMRService | None = None


def _get_service() -> GitLabMRService:
    global _service
    if _service is None:
        _service = GitLabMRService()
    return _service


@router.get("/merge-requests", response_model=MergeRequestListResponse)
async def list_merge_requests(
    state: str = Query(default="opened", description="GitLab MR state: opened, merged, closed, all"),
    limit: int = Query(default=50, ge=1, le=100),
    target_branch: str | None = Query(default=None),
):
    try:
        mrs = await _get_service().list_merge_requests(
            state=state,
            limit=limit,
            target_branch=target_branch,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc

    return MergeRequestListResponse(
        count=len(mrs),
        merge_requests=[MergeRequestListItem(**mr) for mr in mrs],
    )


@router.get("/merge-requests/by-environment", response_model=MergeRequestByEnvironmentResponse)
async def list_merge_requests_by_environment(
    limit: int = Query(default=40, ge=1, le=100),
):
    try:
        data = await _get_service().list_merge_requests_by_environment(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc
    return MergeRequestByEnvironmentResponse(**data)


@router.get("/merge-requests/{mr_iid}/status", response_model=MergeRequestStatusResponse)
async def get_merge_request_status(mr_iid: int):
    try:
        status = await _get_service().get_mr_status(mr_iid)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MergeRequestStatusResponse(mr_iid=mr_iid, **status)


@router.get(
    "/merge-requests/{mr_iid}/review-context",
    response_model=MergeRequestReviewContextResponse,
)
async def get_review_context(mr_iid: int):
    """Build and return the review prompt/context without calling the LLM."""
    try:
        result = await _get_service().prepare_review_context(mr_iid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MergeRequestReviewContextResponse(**result)


@router.get(
    "/merge-requests/{mr_iid}/last-review",
    response_model=MergeRequestLastReviewResponse,
)
async def get_last_merge_request_review(mr_iid: int):
    """Return the latest Sentinel review stored for this MR (survives page refresh)."""
    result = await _get_service().get_last_review_for_mr(mr_iid)
    if not result:
        raise HTTPException(status_code=404, detail=f"No review found for MR !{mr_iid}")
    return MergeRequestLastReviewResponse(**result)


@router.post("/merge-requests/{mr_iid}/review", response_model=MergeRequestReviewResponse)
async def review_merge_request(mr_iid: int, request: MergeRequestReviewRequest | None = None):
    """Trigger Sentinel review: knowledge package → Cursor CLI agent → GitLab comment → HITL."""
    request = request or MergeRequestReviewRequest()
    try:
        result = await _get_service().review_merge_request(
            mr_iid=mr_iid,
            reviewed_by=request.reviewed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MergeRequestReviewResponse(**result)


@router.post("/merge-requests/{mr_iid}/merge", response_model=MergeRequestMergeResponse)
async def merge_merge_request(mr_iid: int, request: MergeRequestMergeRequest | None = None):
    """Merge MR after pipeline success (no conflicts)."""
    request = request or MergeRequestMergeRequest()
    try:
        result = await _get_service().merge_merge_request(
            mr_iid=mr_iid,
            merged_by=request.merged_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MergeRequestMergeResponse(**result)
