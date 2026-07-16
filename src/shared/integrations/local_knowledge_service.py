from typing import Any

from shared.integrations.protocols import KnowledgeServiceProtocol
from slices.knowledge.service import KnowledgeRAGService


class LocalRAGKnowledgeService(KnowledgeServiceProtocol):
    """ChromaDB-backed local RAG knowledge service."""

    def __init__(self):
        self._service = KnowledgeRAGService()

    async def query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        collections = (context or {}).get("collections")
        if collections:
            results = self._service._store.query(
                question=question,
                collections=collections,
                top_k=top_k,
            )
        else:
            results = await self._service.query_raw(question=question, context=context, top_k=top_k)
        return [
            {
                "score": r["score"],
                "content": r["content"],
                "source": r["collection"],
                "title": r.get("title"),
            }
            for r in results
        ]

    async def get_architecture_context(self, topic: str) -> str:
        return await self._service.get_architecture_context(topic)
