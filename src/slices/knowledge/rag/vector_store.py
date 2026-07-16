"""ChromaDB vector store for knowledge RAG."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.config import get_settings
from slices.knowledge.models.collections import ALL_COLLECTIONS, COLLECTION_LABELS


def _ensure_chroma_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _is_valid_api_key(key: str) -> bool:
    placeholders = {"", "your-api-key", "mock-key", "changeme"}
    return bool(key) and key not in placeholders


def _build_embedding_function():
    settings = get_settings()
    if _is_valid_api_key(settings.llm_api_key):
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=settings.llm_api_key,
            api_base=settings.llm_base_url,
            model_name=settings.embedding_model,
        )
    return embedding_functions.DefaultEmbeddingFunction()


SEED_DOCUMENTS: list[dict[str, Any]] = [
    {
        "collection": "code_patterns",
        "title": "CQRS Command Handler Pattern",
        "content": (
            "Use MediatR ICommandHandler<TCommand> for write operations. "
            "Commands should be immutable records. Validate with FluentValidation "
            "before handler execution. Return Result<T> for domain errors."
        ),
        "tags": ["cqrs", "mediatr", "dotnet"],
    },
    {
        "collection": "code_patterns",
        "title": "Vertical Slice API Structure",
        "content": (
            "Organize features as vertical slices: Endpoint -> Command/Query -> Handler -> Domain. "
            "Keep controllers thin. Map endpoints with minimal API or controllers in .NET 8."
        ),
        "tags": ["architecture", "vertical-slice"],
    },
    {
        "collection": "solutions",
        "title": "Contract API Implementation",
        "content": (
            "Contract CRUD implemented with aggregate root Contract, repository pattern, "
            "Redis cache for GET by ID, RabbitMQ ContractCreated event on create."
        ),
        "tags": ["contract", "api"],
        "task_key": "VEN-100",
    },
    {
        "collection": "error_patterns",
        "title": "Payment Gateway Timeout",
        "content": (
            "Symptom: 504 on POST /api/v1/payments, ConnectionTimeout to payment-service. "
            "Root cause: external PSP timeout. Fix: verify Polly circuit breaker, increase timeout, "
            "check PSP health. Fallback: return 503 with retry-after header."
        ),
        "tags": ["payment", "timeout", "504"],
    },
    {
        "collection": "best_practices",
        "title": "EF Core Migrations",
        "content": (
            "Always create migration per vertical slice change. "
            "Use explicit configuration in IEntityTypeConfiguration. "
            "Never modify applied migrations in production."
        ),
        "tags": ["efcore", "mysql"],
    },
    {
        "collection": "historical_context",
        "title": "Similar Task VEN-95 Redis Caching",
        "content": (
            "Task VEN-95 added Redis distributed cache for query handlers. "
            "Pattern: ICacheService wrapper, 5min TTL, cache-aside. "
            "Applied to contract and catalog queries successfully."
        ),
        "tags": ["redis", "caching"],
        "task_key": "VEN-95",
    },
]


class ChromaKnowledgeStore:
    """Persistent ChromaDB store with one collection per knowledge category."""

    def __init__(self, persist_path: str | None = None):
        settings = get_settings()
        self._path = persist_path or settings.knowledge_chroma_path
        _ensure_chroma_dir(self._path)
        self._client = chromadb.PersistentClient(path=self._path)
        self._embedding_fn = _build_embedding_function()
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " "],
        )
        self._collections: dict[str, Any] = {}
        for name in ALL_COLLECTIONS:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                embedding_function=self._embedding_fn,
                metadata={"label": COLLECTION_LABELS.get(name, name)},
            )

    def _collection(self, name: str):
        if name not in self._collections:
            raise ValueError(f"Unknown collection: {name}")
        return self._collections[name]

    def seed_defaults_if_empty(self) -> int:
        total_chunks = sum(self._collection(name).count() for name in ALL_COLLECTIONS)
        if total_chunks > 0:
            return 0

        seeded = 0
        for doc in SEED_DOCUMENTS:
            self.ingest(
                collection=doc["collection"],
                title=doc["title"],
                content=doc["content"],
                tags=doc.get("tags", []),
                task_key=doc.get("task_key"),
                source="seed",
            )
            seeded += 1
        return seeded

    def ingest(
        self,
        collection: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        source: str | None = None,
        task_key: str | None = None,
        doc_id: str | None = None,
    ) -> dict[str, Any]:
        doc_id = doc_id or str(uuid.uuid4())
        chunks = self._splitter.split_text(content)
        if not chunks:
            chunks = [content]

        col = self._collection(collection)
        chunk_ids = [f"{doc_id}__chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_id": doc_id,
                "title": title,
                "collection": collection,
                "chunk_index": i,
                "tags": ",".join(tags or []),
                "source": source or "manual",
                "task_key": task_key or "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(len(chunks))
        ]
        col.add(ids=chunk_ids, documents=chunks, metadatas=metadatas)
        return {"id": doc_id, "chunks_created": len(chunks)}

    def query(
        self,
        question: str,
        collections: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        targets = collections or ALL_COLLECTIONS
        all_results: list[dict[str, Any]] = []

        for name in targets:
            col = self._collection(name)
            if col.count() == 0:
                continue
            result = col.query(query_texts=[question], n_results=min(top_k, col.count()))
            if not result["ids"] or not result["ids"][0]:
                continue
            for i, chunk_id in enumerate(result["ids"][0]):
                distance = result["distances"][0][i] if result.get("distances") else 0
                score = max(0.0, 1.0 - distance)
                meta = result["metadatas"][0][i] if result.get("metadatas") else {}
                all_results.append(
                    {
                        "id": chunk_id,
                        "doc_id": meta.get("doc_id", chunk_id),
                        "content": result["documents"][0][i],
                        "score": round(score, 4),
                        "collection": name,
                        "title": meta.get("title"),
                        "metadata": meta,
                    }
                )

        all_results.sort(key=lambda r: r["score"], reverse=True)
        return all_results[:top_k]

    def list_documents(self, collection: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        targets = [collection] if collection else ALL_COLLECTIONS
        docs: dict[str, dict[str, Any]] = {}

        for name in targets:
            col = self._collection(name)
            if col.count() == 0:
                continue
            data = col.get(include=["documents", "metadatas"])
            for i, chunk_id in enumerate(data["ids"]):
                meta = data["metadatas"][i] if data.get("metadatas") else {}
                doc_id = meta.get("doc_id", chunk_id)
                if doc_id in docs:
                    continue
                content = data["documents"][i] if data.get("documents") else ""
                docs[doc_id] = {
                    "id": doc_id,
                    "collection": name,
                    "title": meta.get("title", "Untitled"),
                    "content_preview": content[:200],
                    "tags": [t for t in meta.get("tags", "").split(",") if t],
                    "source": meta.get("source") or None,
                    "task_key": meta.get("task_key") or None,
                    "created_at": meta.get("created_at"),
                }
                if len(docs) >= limit:
                    break

        return list(docs.values())[:limit]

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        for name in ALL_COLLECTIONS:
            col = self._collection(name)
            data = col.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
            if not data.get("ids"):
                continue
            chunks: list[str] = []
            meta = data["metadatas"][0] if data.get("metadatas") else {}
            for i, chunk_id in enumerate(data["ids"]):
                content = data["documents"][i] if data.get("documents") else ""
                chunks.append(content)
            full_content = "\n\n".join(chunks)
            return {
                "id": doc_id,
                "collection": name,
                "title": meta.get("title", "Untitled"),
                "content": full_content,
                "content_preview": full_content[:300],
                "tags": [t for t in meta.get("tags", "").split(",") if t],
                "source": meta.get("source") or None,
                "task_key": meta.get("task_key") or None,
                "created_at": meta.get("created_at"),
                "chunk_count": len(chunks),
            }
        return None

    def delete_document(self, doc_id: str) -> int:
        deleted = 0
        for name in ALL_COLLECTIONS:
            col = self._collection(name)
            existing = col.get(where={"doc_id": doc_id}, include=[])
            if existing["ids"]:
                col.delete(ids=existing["ids"])
                deleted += len(existing["ids"])
        return deleted

    def get_stats(self) -> dict[str, Any]:
        settings = get_settings()
        collection_counts: dict[str, int] = {}
        total_chunks = 0
        doc_ids: set[str] = set()

        for name in ALL_COLLECTIONS:
            col = self._collection(name)
            count = col.count()
            collection_counts[name] = count
            total_chunks += count
            if count > 0:
                data = col.get(include=["metadatas"])
                for meta in data.get("metadatas") or []:
                    if meta and meta.get("doc_id"):
                        doc_ids.add(meta["doc_id"])

        return {
            "total_documents": len(doc_ids),
            "total_chunks": total_chunks,
            "collections": collection_counts,
            "chroma_path": str(Path(self._path).resolve()),
            "embedding_model": settings.embedding_model
            if _is_valid_api_key(settings.llm_api_key)
            else "default-local (all-MiniLM-L6-v2)",
        }


@lru_cache
def get_knowledge_store() -> ChromaKnowledgeStore:
    store = ChromaKnowledgeStore()
    store.seed_defaults_if_empty()
    return store
