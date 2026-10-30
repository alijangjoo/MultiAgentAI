"""API routes for RTK token savings dashboard."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from shared.cursor_cli.rtk_compress import fetch_rtk_cli_gain_json, is_rtk_available
from shared.rtk.savings_repository import RtkSavingsRepository

router = APIRouter(prefix="/api/v1/rtk", tags=["rtk"])


class RtkSavingsItem(BaseModel):
    id: str
    run_id: str | None = None
    workflow_type: str
    source: str
    method: str
    mr_iid: int | None = None
    task_key: str | None = None
    raw_tokens: int
    compressed_tokens: int
    tokens_saved: int
    savings_pct: float
    raw_chars: int
    compressed_chars: int
    rtk_available: bool
    note: str
    created_at: str


class RtkMethodStats(BaseModel):
    method: str
    count: int
    tokens_saved: int


class RtkAggregateStats(BaseModel):
    total_events: int
    total_raw_tokens: int
    total_compressed_tokens: int
    total_tokens_saved: int
    overall_savings_pct: float
    rtk_binary_available: bool
    by_method: list[RtkMethodStats]


class RtkSavingsListResponse(BaseModel):
    items: list[RtkSavingsItem]
    stats: RtkAggregateStats


class RtkCliGainResponse(BaseModel):
    installed: bool
    data: dict | None = None
    message: str = ""


@router.get("/savings", response_model=RtkSavingsListResponse)
async def list_rtk_savings(limit: int = 100):
    repo = RtkSavingsRepository()
    items = await repo.list_records(limit=min(limit, 500))
    stats = await repo.aggregate_stats()
    return RtkSavingsListResponse(
        items=[RtkSavingsItem(**item) for item in items],
        stats=RtkAggregateStats(**stats),
    )


@router.get("/stats", response_model=RtkAggregateStats)
async def rtk_aggregate_stats():
    repo = RtkSavingsRepository()
    return RtkAggregateStats(**(await repo.aggregate_stats()))


@router.get("/gain", response_model=RtkCliGainResponse)
async def rtk_cli_gain():
    """Proxy RTK CLI `gain --all --format json` for dashboard (global shell hook stats)."""
    if not is_rtk_available():
        return RtkCliGainResponse(
            installed=False,
            message="RTK binary not found. Install from https://github.com/rtk-ai/rtk/releases",
        )
    data = await asyncio.to_thread(fetch_rtk_cli_gain_json)
    if data is None:
        return RtkCliGainResponse(
            installed=True,
            message="RTK installed but `rtk gain` failed or timed out",
        )
    if data.get("error"):
        return RtkCliGainResponse(installed=True, data=data, message=str(data["error"]))
    return RtkCliGainResponse(installed=True, data=data, message="ok")


class RtkHealthResponse(BaseModel):
    rtk_installed: bool
    rtk_bin: str | None = None
    review_use_rtk: bool = True


@router.get("/health", response_model=RtkHealthResponse)
async def rtk_health():
    from core.config import get_settings
    from shared.cursor_cli.rtk_compress import resolve_rtk_bin

    settings = get_settings()
    bin_path = resolve_rtk_bin()
    return RtkHealthResponse(
        rtk_installed=bin_path is not None,
        rtk_bin=bin_path,
        review_use_rtk=settings.cursor_review_use_rtk,
    )
