from typing import Any

from shared.integrations.protocols import KnowledgeServiceProtocol


class MockKnowledgeService(KnowledgeServiceProtocol):
    _KNOWLEDGE_BASE: dict[str, str] = {
        "cqrs": (
            "CQRS pattern: Separate Command and Query handlers using MediatR. "
            "Commands modify state, Queries read state. "
            "Use ICommandHandler<T> and IQueryHandler<T> interfaces."
        ),
        "contract": (
            "Contract domain: Aggregate root Contract with Value Objects "
            "ContractNumber, ContractStatus. Events: ContractCreated, ContractUpdated."
        ),
        "payment": (
            "Payment service integrates with external PSP via HTTP. "
            "Circuit breaker pattern implemented with Polly. "
            "Timeout configured at 30 seconds. Fallback returns 503."
        ),
        "architecture": (
            "Vertical slice architecture with Domain, Application, Infrastructure layers. "
            "MySQL for persistence, Redis for caching, RabbitMQ for domain events."
        ),
    }

    async def query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        question_lower = question.lower()
        results = []
        for key, content in self._KNOWLEDGE_BASE.items():
            if key in question_lower or any(w in content.lower() for w in question_lower.split()):
                results.append({"score": 0.9, "content": content, "source": key})
        if not results:
            results.append(
                {
                    "score": 0.5,
                    "content": self._KNOWLEDGE_BASE["architecture"],
                    "source": "architecture",
                }
            )
        return results[:top_k]

    async def get_architecture_context(self, topic: str) -> str:
        results = await self.query(topic)
        return "\n\n".join(r["content"] for r in results)


class RealKnowledgeService(KnowledgeServiceProtocol):
    def __init__(self, url: str, api_key: str):
        self._url = url.rstrip("/")
        self._api_key = api_key

    async def query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._url}/api/v1/query",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"question": question, "context": context or {}, "top_k": top_k},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json().get("results", [])

    async def get_architecture_context(self, topic: str) -> str:
        results = await self.query(topic, top_k=3)
        return "\n\n".join(r.get("content", "") for r in results)
