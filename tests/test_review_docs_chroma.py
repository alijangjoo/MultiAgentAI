from typing import Any

import pytest

from slices.knowledge import review_docs


class FakeKnowledgeStore:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def list_documents(
        self, collection: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = []
        for doc in self.documents.values():
            if collection and doc["collection"] != collection:
                continue
            rows.append(
                {
                    "id": doc["id"],
                    "collection": doc["collection"],
                    "title": doc["title"],
                    "content_preview": doc["content"][:200],
                    "tags": doc["tags"],
                    "source": doc["source"],
                    "created_at": None,
                }
            )
        return rows[:limit]

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        doc = self.documents.get(doc_id)
        if not doc:
            return None
        return {**doc, "chunk_count": 1}

    def upsert_document(
        self,
        collection: str,
        title: str,
        content: str,
        *,
        doc_id: str,
        tags: list[str] | None = None,
        source: str | None = None,
        task_key: str | None = None,
        split: bool = True,
    ) -> dict[str, Any]:
        self.documents[doc_id] = {
            "id": doc_id,
            "collection": collection,
            "title": title,
            "content": content,
            "tags": tags or [],
            "source": source,
            "task_key": task_key,
            "split": split,
        }
        return {"id": doc_id, "chunks_created": 1}

    def delete_document(self, doc_id: str) -> int:
        return 1 if self.documents.pop(doc_id, None) else 0


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> review_docs.ReviewDocsService:
    store = FakeKnowledgeStore()
    monkeypatch.setattr(review_docs, "get_knowledge_store", lambda: store)
    return review_docs.ReviewDocsService()


def test_managed_defaults_are_seeded_in_chroma_without_splitting(
    service: review_docs.ReviewDocsService,
) -> None:
    for kind in ("review-rules", "code-specs", "review-prompt", "agent-documents"):
        items = service.list_managed_documents(kind)
        assert len(items) == 1
        assert items[0]["source"] == "chroma"
        stored = service._store.get_document(items[0]["id"])
        assert stored is not None
        assert stored["split"] is False


def test_prompt_is_loaded_and_updated_only_through_chroma(
    service: review_docs.ReviewDocsService,
) -> None:
    prompt = service.get_prompt_template()
    assert prompt["source"] == "chroma"
    assert prompt["collection"] == "review_prompt"

    updated = prompt["body"] + "\n\nReview run marker."
    result = service.save_prompt_template(updated)

    assert result["applied"] is True
    assert service.get_prompt_template()["body"] == updated


def test_prompt_rejects_missing_or_unknown_placeholders(
    service: review_docs.ReviewDocsService,
) -> None:
    with pytest.raises(ValueError, match="missing required placeholders"):
        service.save_prompt_template("A prompt with {diff} and {review_rules}, but nothing else.")

    valid = service.get_prompt_template()["body"]
    with pytest.raises(ValueError, match="unknown placeholders"):
        service.save_prompt_template(valid + "\n{not_a_real_context}")


def test_collection_text_uses_full_chroma_content(
    service: review_docs.ReviewDocsService,
) -> None:
    content = service.load_collection_text("review_rules", limit_chars=20_000)

    assert "RR-001" in content
    assert "Sentinel Review Rules" in content
