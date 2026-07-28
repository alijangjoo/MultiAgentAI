import asyncio
import json

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.config import get_settings

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
from shared.review.progress import ReviewProgressReporter

router = APIRouter(prefix="/api/v1/gitlab", tags=["gitlab"])

_service: GitLabMRService | None = None


def _get_service() -> GitLabMRService:
    global _service
    if _service is None:
        _service = GitLabMRService()
    return _service


@router.get("/cursor-bridge/health")
async def cursor_bridge_health_proxy():
    """Proxy Bridge /health for the Review dashboard (browser cannot call Bridge directly — no CORS)."""
    settings = get_settings()
    url = f"{settings.cursor_bridge_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Cursor Bridge not reachable at {url}. "
                "Start it with: python run_cursor_bridge.py"
            ),
        ) from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=503,
            detail=f"Cursor Bridge health check failed: HTTP {response.status_code}",
        )
    return response.json()


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


@router.post("/merge-requests/{mr_iid}/review/stream")
async def review_merge_request_stream(
    mr_iid: int, request: MergeRequestReviewRequest | None = None
):
    """Run Sentinel review and stream live step logs (SSE, not persisted)."""
    request = request or MergeRequestReviewRequest()
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    async def emit_event(event: str, payload: dict) -> None:
        await queue.put((event, payload))

    progress = ReviewProgressReporter(emit_event=emit_event)

    async def run_review() -> None:
        try:
            result = await _get_service().review_merge_request(
                mr_iid=mr_iid,
                reviewed_by=request.reviewed_by,
                progress=progress,
            )
            await queue.put(("result", result))
        except ValueError as exc:
            await queue.put(("error", {"message": str(exc), "status": 400}))
        except Exception as exc:
            await queue.put(("error", {"message": str(exc), "status": 500}))
        finally:
            await queue.put(None)

    asyncio.create_task(run_review())

    async def event_stream():
        while True:
            item = await queue.get()
            if item is None:
                break
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
