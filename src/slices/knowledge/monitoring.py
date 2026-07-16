"""Aggregated monitoring data for the Sage Knowledge Agent dashboard."""

from typing import Any

from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.models.collections import COLLECTION_LABELS
from slices.knowledge.models.schemas import (
    KnowledgeEventItem,
    KnowledgeMonitoringResponse,
    KnowledgeRunSummary,
    KnowledgeStatsResponse,
)
from slices.knowledge.rag.vector_store import get_knowledge_store


def _summarize_run(run: dict[str, Any]) -> KnowledgeRunSummary:
    inp = run.get("input_payload") or {}
    out = run.get("output_payload") or {}
    question = inp.get("question")
    source = inp.get("source")
    if not source and inp.get("action"):
        source = inp.get("action")

    answer_preview = out.get("answer")
    if isinstance(answer_preview, str):
        answer_preview = answer_preview[:200]

    documents_ingested = out.get("documents_ingested")
    chunks_created = out.get("chunks_created")

    return KnowledgeRunSummary(
        id=run["id"],
        workflow_type=run["workflow_type"],
        status=run["status"],
        created_at=run["created_at"],
        updated_at=run["updated_at"],
        question=question,
        source=source or inp.get("source"),
        documents_ingested=documents_ingested,
        chunks_created=chunks_created,
        answer_preview=answer_preview,
        error_message=run.get("error_message"),
    )


class KnowledgeMonitoringService:
    KNOWLEDGE_WORKFLOWS = {
        WorkflowType.KNOWLEDGE_QUERY.value,
        WorkflowType.KNOWLEDGE_INGEST.value,
    }

    def __init__(self, run_repo: AgentRunRepository | None = None):
        self._store = get_knowledge_store()
        self._run_repo = run_repo or AgentRunRepository()

    def get_stats(self) -> KnowledgeStatsResponse:
        return KnowledgeStatsResponse(**self._store.get_stats())

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        return self._store.get_document(doc_id)

    async def get_monitoring_snapshot(self, runs_limit: int = 30) -> KnowledgeMonitoringResponse:
        stats_raw = self._store.get_stats()
        stats = KnowledgeStatsResponse(**stats_raw)

        all_runs = await self._run_repo.list_runs(
            agent_name=AgentName.SAGE,
            limit=runs_limit * 2,
        )
        knowledge_runs = [
            r for r in all_runs if r["workflow_type"] in self.KNOWLEDGE_WORKFLOWS
        ][:runs_limit]

        run_summary = {
            "total": len(knowledge_runs),
            "running": sum(1 for r in knowledge_runs if r["status"] == RunStatus.RUNNING.value),
            "completed": sum(1 for r in knowledge_runs if r["status"] == RunStatus.COMPLETED.value),
            "failed": sum(1 for r in knowledge_runs if r["status"] == RunStatus.FAILED.value),
            "queries": sum(
                1 for r in knowledge_runs if r["workflow_type"] == WorkflowType.KNOWLEDGE_QUERY.value
            ),
            "ingests": sum(
                1 for r in knowledge_runs if r["workflow_type"] == WorkflowType.KNOWLEDGE_INGEST.value
            ),
        }

        events_raw = await self._run_repo.list_events_by_agent(AgentName.SAGE, limit=80)
        recent_events = [KnowledgeEventItem(**e) for e in events_raw]

        collections = [
            {
                "id": key,
                "label": label,
                "chunks": stats_raw["collections"].get(key, 0),
            }
            for key, label in COLLECTION_LABELS.items()
        ]

        chroma_healthy = stats.total_chunks >= 0

        return KnowledgeMonitoringResponse(
            stats=stats,
            collections=collections,
            run_summary=run_summary,
            recent_runs=[_summarize_run(r) for r in knowledge_runs],
            recent_events=recent_events,
            chroma_healthy=chroma_healthy,
        )

    async def get_run_detail(self, run_id: str) -> dict[str, Any] | None:
        run = await self._run_repo.get_run(run_id)
        if not run or run.get("agent_name") != AgentName.SAGE.value:
            return None
        events = await self._run_repo.get_events(run_id)
        return {"run": run, "events": events}
