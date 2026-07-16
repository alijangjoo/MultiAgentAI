from typing import Any

from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.agents.sage import run_sage
from slices.knowledge.models.collections import ALL_COLLECTIONS
from slices.knowledge.models.schemas import (
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeQueryResultItem,
    KnowledgeStatsResponse,
)
from slices.knowledge.rag.vector_store import get_knowledge_store


class KnowledgeRAGService:
    def __init__(self, run_repo: AgentRunRepository | None = None):
        self._store = get_knowledge_store()
        self._run_repo = run_repo or AgentRunRepository()

    async def query(self, request: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        collections = [c.value for c in request.collections] if request.collections else None

        if request.synthesize:
            run_id = await self._run_repo.create_run(
                workflow_type=WorkflowType.KNOWLEDGE_QUERY.value,
                agent_name=AgentName.SAGE,
                input_payload=request.model_dump(mode="json"),
            )
            await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)
            try:
                result = await run_sage(
                    run_id=run_id,
                    question=request.question,
                    collections=collections,
                    top_k=request.top_k,
                    context=request.context,
                    repo=self._run_repo,
                )
                await self._run_repo.update_run(
                    run_id,
                    status=RunStatus.COMPLETED,
                    output_payload={"answer": result.get("answer"), "results_count": len(result.get("results", []))},
                )
                results = result.get("results", [])
                answer = result.get("answer")
            except Exception as exc:
                await self._run_repo.update_run(run_id, status=RunStatus.FAILED, error_message=str(exc))
                raise
        else:
            run_id = None
            results = self._store.query(
                question=request.question,
                collections=collections,
                top_k=request.top_k,
            )
            answer = None

        return KnowledgeQueryResponse(
            question=request.question,
            answer=answer,
            results=[KnowledgeQueryResultItem(**r) for r in results],
            collections_searched=collections or ALL_COLLECTIONS,
            run_id=run_id,
        )

    async def ingest(self, request: KnowledgeIngestRequest) -> KnowledgeIngestResponse:
        result = self._store.ingest(
            collection=request.collection.value,
            title=request.title,
            content=request.content,
            tags=request.tags,
            source=request.source,
            task_key=request.task_key,
        )
        return KnowledgeIngestResponse(
            id=result["id"],
            collection=request.collection.value,
            title=request.title,
            chunks_created=result["chunks_created"],
            message=f"Document ingested into {request.collection.value}",
        )

    def list_documents(self, collection: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.list_documents(collection=collection, limit=limit)

    def delete_document(self, doc_id: str) -> int:
        return self._store.delete_document(doc_id)

    def get_stats(self) -> KnowledgeStatsResponse:
        return KnowledgeStatsResponse(**self._store.get_stats())

    async def query_raw(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Used by Forge/Atlas/Aegis via KnowledgeServiceProtocol."""
        return self._store.query(question=question, top_k=top_k)

    async def get_architecture_context(self, topic: str) -> str:
        results = self._store.query(question=topic, top_k=3)
        return "\n\n".join(r["content"] for r in results)
