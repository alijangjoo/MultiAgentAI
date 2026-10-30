"""Persist and query RTK compression savings for the dashboard."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from shared.cursor_cli.rtk_compress import DiffCompressResult, is_rtk_available
from shared.persistence.database import get_session
from shared.persistence.models import RtkSavingsRecord


class RtkSavingsRepository:
    async def create_from_result(
        self,
        result: DiffCompressResult,
        *,
        run_id: str | None = None,
        workflow_type: str = "mr_code_review",
        source: str = "review",
        mr_iid: int | None = None,
        task_key: str | None = None,
    ) -> str:
        record_id = str(uuid4())
        tokens_saved = max(0, result.raw_tokens - result.compressed_tokens)
        async with get_session() as session:
            session.add(
                RtkSavingsRecord(
                    id=record_id,
                    run_id=run_id,
                    workflow_type=workflow_type,
                    source=source,
                    method=result.method,
                    mr_iid=mr_iid,
                    task_key=task_key,
                    raw_tokens=result.raw_tokens,
                    compressed_tokens=result.compressed_tokens,
                    tokens_saved=tokens_saved,
                    savings_pct=result.savings_pct,
                    raw_chars=result.raw_chars,
                    compressed_chars=result.compressed_chars,
                    rtk_available=is_rtk_available(),
                    note=result.note,
                )
            )
        return record_id

    async def list_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        async with get_session() as session:
            result = await session.execute(
                select(RtkSavingsRecord)
                .order_by(RtkSavingsRecord.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [self._to_dict(r) for r in rows]

    async def aggregate_stats(self) -> dict[str, Any]:
        async with get_session() as session:
            result = await session.execute(
                select(
                    func.count(RtkSavingsRecord.id),
                    func.coalesce(func.sum(RtkSavingsRecord.raw_tokens), 0),
                    func.coalesce(func.sum(RtkSavingsRecord.compressed_tokens), 0),
                    func.coalesce(func.sum(RtkSavingsRecord.tokens_saved), 0),
                )
            )
            count, raw_sum, compressed_sum, saved_sum = result.one()
            raw_sum = int(raw_sum or 0)
            compressed_sum = int(compressed_sum or 0)
            saved_sum = int(saved_sum or 0)
            savings_pct = (
                (saved_sum / raw_sum * 100.0) if raw_sum > 0 else 0.0
            )

            by_method_result = await session.execute(
                select(
                    RtkSavingsRecord.method,
                    func.count(RtkSavingsRecord.id),
                    func.coalesce(func.sum(RtkSavingsRecord.tokens_saved), 0),
                ).group_by(RtkSavingsRecord.method)
            )
            by_method = [
                {
                    "method": row[0],
                    "count": int(row[1]),
                    "tokens_saved": int(row[2] or 0),
                }
                for row in by_method_result.all()
            ]

        return {
            "total_events": int(count or 0),
            "total_raw_tokens": raw_sum,
            "total_compressed_tokens": compressed_sum,
            "total_tokens_saved": saved_sum,
            "overall_savings_pct": round(savings_pct, 1),
            "rtk_binary_available": is_rtk_available(),
            "by_method": by_method,
        }

    @staticmethod
    def _to_dict(record: RtkSavingsRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "run_id": record.run_id,
            "workflow_type": record.workflow_type,
            "source": record.source,
            "method": record.method,
            "mr_iid": record.mr_iid,
            "task_key": record.task_key,
            "raw_tokens": record.raw_tokens,
            "compressed_tokens": record.compressed_tokens,
            "tokens_saved": record.tokens_saved,
            "savings_pct": record.savings_pct,
            "raw_chars": record.raw_chars,
            "compressed_chars": record.compressed_chars,
            "rtk_available": record.rtk_available,
            "note": record.note,
            "created_at": record.created_at.isoformat(),
        }


async def persist_rtk_savings(
    result: DiffCompressResult,
    *,
    run_id: str | None = None,
    source: str = "review",
    mr_iid: int | None = None,
    task_key: str | None = None,
    workflow_type: str = "mr_code_review",
) -> str | None:
    """Store one RTK compression event."""
    from core.config import get_settings

    if not get_settings().cursor_review_use_rtk:
        return None
    repo = RtkSavingsRepository()
    return await repo.create_from_result(
        result,
        run_id=run_id,
        source=source,
        mr_iid=mr_iid,
        task_key=task_key,
        workflow_type=workflow_type,
    )


async def persist_rtk_from_context_extra(
    extra_context: dict | None,
    *,
    git_diff: str,
    git_diff_raw: str | None,
    run_id: str | None = None,
    source: str = "review_context",
    mr_iid: int | None = None,
    task_key: str | None = None,
) -> str | None:
    """Persist savings recorded in ReviewContext.extra_context['rtk_stats']."""
    if not extra_context:
        return None
    stats = extra_context.get("rtk_stats")
    if not isinstance(stats, dict):
        return None
    result = DiffCompressResult(
        compressed=git_diff,
        raw=git_diff_raw or git_diff,
        method=stats.get("method", "none"),
        raw_chars=int(stats.get("raw_chars") or len(git_diff_raw or git_diff)),
        compressed_chars=int(stats.get("compressed_chars") or len(git_diff)),
        raw_tokens=int(stats.get("raw_tokens") or 0),
        compressed_tokens=int(stats.get("compressed_tokens") or 0),
        savings_pct=float(stats.get("savings_pct") or 0),
    )
    return await persist_rtk_savings(
        result,
        run_id=run_id,
        source=source,
        mr_iid=mr_iid,
        task_key=task_key,
    )
