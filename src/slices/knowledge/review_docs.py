"""Chroma-backed management for all documents used by Sentinel reviews."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from core.config import get_settings
from slices.knowledge.models.collections import KnowledgeCollection
from slices.knowledge.rag.vector_store import get_knowledge_store

_PROMPT_PLACEHOLDERS = (
    "tech_stack",
    "jira_ticket",
    "prd",
    "adrs",
    "code_specs",
    "architecture_specs",
    "source_context",
    "ubiquitous_language",
    "diff",
    "review_rules",
    "mr_title",
    "source_branch",
    "target_branch",
    "development_summary",
)

_DEFAULT_PROMPT = """[CONTEXT]
Project Architecture: Onion + Vertical Slice
Tech Stack: {tech_stack}
MR: {mr_title} ({source_branch} → {target_branch})
JIRA Ticket: {jira_ticket}
Development Summary: {development_summary}

[TASK PRD]
{prd}

[CODE SPECS]
{code_specs}

[ARCHITECTURE SPECS]
{architecture_specs}

[ADR]
{adrs}

[UBIQUITOUS LANGUAGE]
{ubiquitous_language}

[CODEBASE CONTEXT]
{source_context}

[MR CHANGES]
{diff}

[REVIEW RULES]
{review_rules}

[TASK]
You are Sentinel, an expert .NET code reviewer for the Dizi codebase.

Review only the supplied MR changes against the supplied Task PRD, Code Specs,
Architecture/ADR/UL context, and Review Rules. Treat Review Rules as the sole
authority for severity and merge-blocking decisions. Treat Code Specs as the
technical reference; do not invent requirements that are absent from the context.

Return one JSON object with keys: approved (bool), summary (string),
findings (array of strings), suggestions (array of strings).
Each findings/suggestions item MUST be a single string like "[ERROR] path/File.cs:12 - message", not an object.
Use LINE=0 when unknown. Set approved=false when the active Review Rules make
any finding merge-blocking.
"""

_DEFAULT_REVIEW_RULES = """# Sentinel Review Rules

Rules define review decisions and severity. Technical implementation details belong in Code Specs.

- RR-001 [ERROR] Domain must not reference Infrastructure, Application, Endpoints, or external application projects.
- RR-002 [ERROR] Queries must not mutate state or perform write side effects.
- RR-003 [ERROR] Secrets, credentials, or private keys must not be committed.
- RR-004 [ERROR] Authorization or tenancy checks must not be bypassed.
- RR-005 [WARNING] Async I/O paths should accept and propagate CancellationToken.
- RR-006 [WARNING] Request paths must not use .Result, .Wait(), or GetAwaiter().GetResult().
- RR-007 [WARNING] Empty catch blocks are not allowed; failures must be logged or mapped intentionally.
- RR-008 [WARNING] Endpoint methods should remain thin and delegate business behavior to Application.
- RR-009 [WARNING] Public Application entry points should follow the active Code Specs.
- RR-010 [SUGGESTION] Prefer established Ubiquitous Language terms over new synonyms.
"""

_DEFAULT_CODE_SPECS = """# Dizi Code Specs

Specs define accepted technical structure and examples. They do not assign review severity.

## Architecture
- .NET 8, Onion Architecture, Vertical Slice, CQRS, and DDD where UL exists.
- Domain contains entities, value objects, invariants, and domain services.
- Application contains use cases, DTOs, validators, and ports.
- Infrastructure implements persistence, messaging, and external integrations.
- Endpoints map transport contracts and authorization to Application calls.

## Application service pattern
- One primary entry method named Execute or ExecuteAsync.
- Use a request DTO when a public method would require more than three parameters.
- Keep one focused use case per service.
- Propagate CancellationToken through async I/O.

## Persistence and integrations
- DbContext and EF configuration remain in Infrastructure.
- Application depends on ports/interfaces, not concrete SDK clients.
- Retriable consumers should be idempotent.

## Naming and tests
- Use terms from the matching Ubiquitous Language.
- Cover changed domain invariants and critical Application behavior.
"""

_DEFAULT_AGENT_DOCUMENTS = """# Sentinel Knowledge Document Catalog

This catalog describes ownership and separation of review knowledge:

- Review Rules (`review_rules`): enforceable checks and severity only.
- Code Specs (`code_specs`): accepted technical structures and examples; no severity.
- Review Prompt (`review_prompt`): orchestration, placeholders, and output contract only.
- Agent Documents (`agent_documents`): governance and collection ownership; never injected into a review prompt.
- Architecture Specs (`architecture_spec`), ADR (`adr`), and Ubiquitous Language (`ubiquitous_language`): optional domain context.

All active content is stored, edited, and read from ChromaDB. Physical markdown files are not runtime sources.
"""

_MANAGED_KINDS: dict[str, tuple[str, str, str, str]] = {
    "review-rules": (
        KnowledgeCollection.REVIEW_RULES.value,
        "sentinel-review-rules",
        "Sentinel Review Rules",
        _DEFAULT_REVIEW_RULES,
    ),
    "code-specs": (
        KnowledgeCollection.CODE_SPECS.value,
        "dizi-code-specs",
        "Dizi Code Specs",
        _DEFAULT_CODE_SPECS,
    ),
    "review-prompt": (
        KnowledgeCollection.REVIEW_PROMPT.value,
        "sentinel-review-prompt",
        "Sentinel Review Prompt Template",
        _DEFAULT_PROMPT,
    ),
    "agent-documents": (
        KnowledgeCollection.AGENT_DOCUMENTS.value,
        "sentinel-agent-documents",
        "Sentinel Agent Document Catalog",
        _DEFAULT_AGENT_DOCUMENTS,
    ),
    "architecture-specs": (
        KnowledgeCollection.ARCHITECTURE_SPEC.value,
        "architecture-spec",
        "Architecture Spec",
        "",
    ),
    "ubiquitous-language": (
        KnowledgeCollection.UBIQUITOUS_LANGUAGE.value,
        "ubiquitous-language",
        "Ubiquitous Language",
        "",
    ),
}


class ReviewDocsService:
    def __init__(self) -> None:
        self._store = get_knowledge_store()
        self.ensure_defaults()

    def ensure_defaults(self) -> dict[str, int]:
        """Seed only missing managed collections; runtime always reads Chroma."""
        seeded: dict[str, int] = {}
        for kind, (collection, doc_id, title, content) in _MANAGED_KINDS.items():
            existing = self._store.list_documents(collection=collection, limit=1)
            if existing:
                seeded[kind] = 0
                continue
            if not content:
                seeded[kind] = 0
                continue
            self._store.upsert_document(
                collection=collection,
                title=title,
                content=content,
                doc_id=doc_id,
                tags=["sentinel", kind, "active"],
                source="chroma-managed",
                split=False,
            )
            seeded[kind] = 1
        return seeded

    @staticmethod
    def _kind_config(kind: str) -> tuple[str, str, str, str]:
        try:
            return _MANAGED_KINDS[kind]
        except KeyError as exc:
            raise ValueError(f"Unknown review document kind: {kind}") from exc

    def list_managed_documents(self, kind: str) -> list[dict[str, Any]]:
        collection, _default_id, _title, _content = self._kind_config(kind)
        items: list[dict[str, Any]] = []
        for item in self._store.list_documents(collection=collection, limit=100):
            detail = self._store.get_document(item["id"]) or {}
            items.append(
                {
                    "id": item["id"],
                    "kind": kind,
                    "collection": collection,
                    "title": item.get("title") or "Untitled",
                    "content": detail.get("content") or "",
                    "content_preview": item.get("content_preview") or "",
                    "tags": item.get("tags") or [],
                    "source": "chroma",
                    "created_at": item.get("created_at"),
                    "chunk_count": detail.get("chunk_count") or 0,
                    "registered": True,
                }
            )
        return sorted(items, key=lambda item: (item["title"].lower(), item["id"]))

    def upsert_managed_document(
        self,
        kind: str,
        *,
        content: str,
        title: str | None = None,
        doc_id: str | None = None,
    ) -> dict[str, Any]:
        collection, default_id, default_title, _default_content = self._kind_config(kind)
        text = (content or "").strip()
        if len(text) < 20:
            raise ValueError("Document content must be at least 20 characters")
        if kind == "review-prompt":
            self.validate_prompt_template(text)
            doc_id = default_id
            title = default_title
        if doc_id:
            stable_id = doc_id.strip()
        elif kind in {
            "review-rules",
            "code-specs",
            "architecture-specs",
            "ubiquitous-language",
        }:
            stable_id = f"{kind}-{uuid4()}"
        else:
            stable_id = default_id
        result = self._store.upsert_document(
            collection=collection,
            title=(title or default_title).strip(),
            content=text,
            doc_id=stable_id,
            tags=["sentinel", kind, "active"],
            source="chroma-managed",
            split=False,
        )
        return {
            "id": stable_id,
            "kind": kind,
            "collection": collection,
            "title": (title or default_title).strip(),
            "content": text,
            "chunks_created": result["chunks_created"],
            "source": "chroma",
            "applied": True,
        }

    def delete_managed_document(self, kind: str, doc_id: str) -> int:
        collection, default_id, _title, _content = self._kind_config(kind)
        detail = self._store.get_document(doc_id)
        if not detail or detail.get("collection") != collection:
            return 0
        if doc_id == default_id and kind in {"review-prompt", "agent-documents"}:
            raise ValueError(f"The active {kind} document cannot be deleted")
        return self._store.delete_document(doc_id)

    def list_review_rule_files(self) -> list[dict[str, Any]]:
        return self.list_managed_documents("review-rules")

    def list_code_spec_files(self) -> list[dict[str, Any]]:
        return self.list_managed_documents("code-specs")

    def list_ul_files(self) -> list[dict[str, Any]]:
        return self._list_collection_documents(
            KnowledgeCollection.UBIQUITOUS_LANGUAGE.value,
            kind="ul",
        )

    def sync_review_rules(self) -> dict[str, Any]:
        self.ensure_defaults()
        return {
            "documents_ingested": 0,
            "collection": KnowledgeCollection.REVIEW_RULES.value,
            "message": "Review Rules are already Chroma-native; Save & Apply updates them directly.",
        }

    def sync_code_specs(self) -> dict[str, Any]:
        self.ensure_defaults()
        return {
            "documents_ingested": 0,
            "collection": KnowledgeCollection.CODE_SPECS.value,
            "message": "Code Specs are already Chroma-native; Save & Apply updates them directly.",
        }

    def sync_ul_file(self, file_path: str) -> dict[str, Any]:
        raise ValueError(
            "Filesystem UL sync is disabled. Create or update the document directly in ChromaDB."
        )

    def sync_all_ul(self) -> dict[str, Any]:
        return {
            "documents_ingested": 0,
            "chunks_created": 0,
            "errors": [],
            "message": "Filesystem UL sync is disabled; ChromaDB is the source of truth.",
        }

    def get_prompt_template(self) -> dict[str, Any]:
        _collection, doc_id, _title, _content = self._kind_config("review-prompt")
        detail = self._store.get_document(doc_id)
        if not detail:
            self.ensure_defaults()
            detail = self._store.get_document(doc_id)
        if not detail:
            raise RuntimeError("Active review prompt is missing from ChromaDB")
        return {
            "id": doc_id,
            "body": str(detail.get("content") or "").strip(),
            "source": "chroma",
            "collection": KnowledgeCollection.REVIEW_PROMPT.value,
            "editable": True,
        }

    def save_prompt_template(self, body: str) -> dict[str, Any]:
        saved = self.upsert_managed_document("review-prompt", content=body)
        return {
            "id": saved["id"],
            "body": saved["content"],
            "source": "chroma",
            "collection": saved["collection"],
            "saved": True,
            "applied": True,
        }

    @staticmethod
    def validate_prompt_template(body: str) -> None:
        required = {"prd", "code_specs", "source_context", "diff", "review_rules"}
        present = set(re.findall(r"\{([a-z_]+)\}", body))
        missing = sorted(required - present)
        unknown = sorted(present - set(_PROMPT_PLACEHOLDERS))
        if missing:
            raise ValueError(
                "Prompt template is missing required placeholders: "
                + ", ".join("{" + key + "}" for key in missing)
            )
        if unknown:
            raise ValueError(
                "Prompt template contains unknown placeholders: "
                + ", ".join("{" + key + "}" for key in unknown)
            )

    def render_review_prompt(
        self,
        *,
        mr_title: str = "",
        source_branch: str = "",
        target_branch: str = "",
        development_summary: str = "",
        jira_ticket: str = "",
        prd: str | None = None,
        diff: str = "",
        tech_stack: str | None = None,
        adrs: str | None = None,
        code_specs: str | None = None,
        architecture_specs: str | None = None,
        source_context: str | None = None,
        review_rules: str | None = None,
        ubiquitous_language: str | None = None,
    ) -> str:
        template = self.get_prompt_template()["body"]
        values = {
            "tech_stack": tech_stack
            or (
                f".NET {get_settings().project_dotnet_version}, Onion + Vertical Slice, "
                "CQRS, DDD, FluentValidation, EF Core (Infrastructure only)"
            ),
            "jira_ticket": jira_ticket or development_summary or "(not provided)",
            "prd": prd if prd is not None else (development_summary or "(no PRD)"),
            "adrs": adrs
            if adrs is not None
            else self.load_collection_text(KnowledgeCollection.ADR.value, 4000),
            "code_specs": code_specs
            if code_specs is not None
            else self.load_collection_text(KnowledgeCollection.CODE_SPECS.value, 6000),
            "architecture_specs": architecture_specs
            if architecture_specs is not None
            else self.load_collection_text(KnowledgeCollection.ARCHITECTURE_SPEC.value, 4000),
            "source_context": source_context
            if source_context is not None
            else (diff or "(no source context)"),
            "ubiquitous_language": ubiquitous_language
            if ubiquitous_language is not None
            else self.load_collection_text(
                KnowledgeCollection.UBIQUITOUS_LANGUAGE.value, 4000
            ),
            "diff": diff or "(no diff provided)",
            "review_rules": review_rules
            if review_rules is not None
            else self.load_collection_text(KnowledgeCollection.REVIEW_RULES.value, 6000),
            "mr_title": mr_title or "(untitled)",
            "source_branch": source_branch or "",
            "target_branch": target_branch or "",
            "development_summary": development_summary or "(none)",
        }
        rendered = template
        for key in _PROMPT_PLACEHOLDERS:
            rendered = rendered.replace("{" + key + "}", str(values.get(key, "")))
        return rendered

    @staticmethod
    def format_mr_diff(mr_changes: list[dict[str, Any]] | None, *, max_chars: int = 20000) -> str:
        if not mr_changes:
            return "(no changes)"
        parts: list[str] = []
        total = 0
        for change in mr_changes[:40]:
            path = change.get("new_path") or change.get("old_path") or "unknown"
            chunk = change.get("diff") or ""
            block = f"### {path}\n{chunk}"
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining > 200:
                    parts.append(block[:remaining] + "\n...[truncated]")
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts) if parts else "(no changes)"

    def load_collection_text(self, collection: str, limit_chars: int = 8000) -> str:
        docs = self._store.list_documents(collection=collection, limit=50)
        parts: list[str] = []
        total = 0
        for doc in docs:
            title = doc.get("title") or ""
            detail = self._store.get_document(doc["id"]) or {}
            content = str(detail.get("content") or "")
            block = f"## {title}\n{content}".strip()
            if not block:
                continue
            if total + len(block) > limit_chars:
                remaining = limit_chars - total
                if remaining > 100:
                    parts.append(block[:remaining] + "\n...[truncated]")
                break
            parts.append(block)
            total += len(block)
        return "\n\n".join(parts) if parts else "(none)"

    def _list_collection_documents(
        self, collection: str, *, kind: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in self._store.list_documents(collection=collection, limit=200):
            detail = self._store.get_document(item["id"]) or {}
            items.append(
                {
                    "id": item["id"],
                    "kind": kind,
                    "title": item.get("title") or "Untitled",
                    "collection": collection,
                    "content": detail.get("content") or "",
                    "registered": True,
                    "source": "chroma",
                    "chunk_count": detail.get("chunk_count") or 0,
                }
            )
        return items


def get_review_docs_service() -> ReviewDocsService:
    return ReviewDocsService()
