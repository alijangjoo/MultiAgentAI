from fastapi import APIRouter, HTTPException, Query

from api.schemas.requests import (
    MergeRequestListItem,
    MergeRequestListResponse,
    MergeRequestReviewRequest,
    MergeRequestReviewResponse,
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
):
    try:
        mrs = await _get_service().list_merge_requests(state=state, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitLab error: {exc}") from exc

    return MergeRequestListResponse(
        count=len(mrs),
        merge_requests=[MergeRequestListItem(**mr) for mr in mrs],
    )


@router.post("/merge-requests/{mr_iid}/review", response_model=MergeRequestReviewResponse)
async def review_merge_request(mr_iid: int, request: MergeRequestReviewRequest | None = None):
    """Trigger Sentinel agent to review an existing merge request."""
    request = request or MergeRequestReviewRequest()
    try:
        result = await _get_service().review_merge_request(
            mr_iid=mr_iid,
            reviewed_by=request.reviewed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MergeRequestReviewResponse(**result)
