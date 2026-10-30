"""Tests for RTK savings persistence."""

import asyncio

from shared.cursor_cli.rtk_compress import DiffCompressResult


def test_persist_and_aggregate_rtk_savings():
    async def _run():
        from shared.persistence.database import init_db
        from shared.rtk.savings_repository import RtkSavingsRepository, persist_rtk_savings

        await init_db()
        result = DiffCompressResult(
            compressed="small",
            raw="x" * 5000,
            method="internal",
            raw_chars=5000,
            compressed_chars=100,
            raw_tokens=1200,
            compressed_tokens=400,
            savings_pct=66.7,
        )
        record_id = await persist_rtk_savings(
            result,
            run_id="test-run-rtk",
            source="test",
            mr_iid=528,
            task_key="VEN-100",
        )
        assert record_id
        repo = RtkSavingsRepository()
        stats = await repo.aggregate_stats()
        assert stats["total_events"] >= 1
        assert stats["total_raw_tokens"] >= 1200

    asyncio.run(_run())
