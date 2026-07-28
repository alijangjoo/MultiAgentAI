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
- RR-012 [WARNING] In every `.cs` file, the `namespace` declaration must be the first code construct (before `using` directives). File-scoped namespaces are preferred.
- RR-013 [ERROR] Every `*CommandHandler.cs` must have a sibling `*CommandValidator.cs` using FluentValidation (`AbstractValidator<TCommand>`).
- RR-014 [WARNING] A `.cs` file must not contain trailing blank lines after the final closing brace. The last line of the file must be `}`.
- RR-015 [WARNING] Application/Infrastructure handlers and services must log at method entry and before each return (structured `ILogger` / `LogInformation` or appropriate level).
- RR-016 [ERROR] `Dizi.AppCore.Domain` must not contain logging, NuGet/package references, or `using` to non-BCL libraries.
"""

_DEFAULT_REVIEW_SKILL = """---
name: sentinel-review
description: Review C# code against Sentinel architecture rules including DDD, CQRS, and logging guidelines
version: 1.1.0
author: Sentinel Team
tags: [csharp, ddd, cqrs, architecture, code-review]
---

# Sentinel Code Review Skill

## Purpose
Review C# MR changes against Sentinel architecture rules: DDD layering, CQRS, file structure, async/logging best practices.

## Output contract
Return one JSON object with keys: `approved` (bool), `summary` (string), `findings` (array of strings), `suggestions` (array of strings).
Each finding/suggestion MUST be a single string like `[ERROR] path/File.cs:12 - message`. Use LINE=0 when unknown.
Set `approved=false` when any merge-blocking rule is violated.

## Rules

### Architecture & Domain Purity

#### RR-001 [ERROR] — Domain layer isolation
Domain must not reference Infrastructure, Application, Endpoints, or external application projects.

Detection pattern:
```regex
using\\s+(Dizi\\.AppCore\\.(Infrastructure|Application|Endpoints)|Microsoft\\.Extensions\\.Logging)
```

#### RR-002 [ERROR] — Query side effects
Queries must not mutate state or perform write side effects.

#### RR-003 [ERROR] — Secrets in source
Secrets, credentials, or private keys must not be committed.

#### RR-004 [ERROR] — Authorization bypass
Authorization or tenancy checks must not be bypassed.

### Async & Logging

#### RR-005 [WARNING] — CancellationToken
Async I/O paths should accept and propagate CancellationToken.

#### RR-006 [WARNING] — Blocking async
Request paths must not use `.Result`, `.Wait()`, or `GetAwaiter().GetResult()`.

#### RR-007 [WARNING] — Empty catch blocks
Empty catch blocks are not allowed; failures must be logged or mapped intentionally.

### Application structure

#### RR-008 [WARNING] — Thin endpoints
Endpoint methods should remain thin and delegate business behavior to Application.

#### RR-009 [WARNING] — Application entry points
Public Application entry points should follow the active Code Specs.

#### RR-010 [SUGGESTION] — Ubiquitous Language
Prefer established Ubiquitous Language terms over new synonyms.

### File layout & CQRS conventions

#### RR-012 [WARNING] — Namespace first
In every `.cs` file, the `namespace` declaration must be the first code construct (before `using` directives). File-scoped namespaces are preferred.

**Correct:**
```csharp
namespace Dizi.AppCore.Domain.ShareDeliveries.Entities;
using Dizi.AppCore.Domain.Base;
public class ShareDelivery : AggregateRoot {}
```

**Wrong:** `using` statements before `namespace`.

Detection: in changed hunks, first non-blank/non-comment line is `using` while `namespace` appears later.

#### RR-013 [ERROR] — CommandValidator sibling
For every new or changed `*CommandHandler.cs`, a matching `*CommandValidator.cs` must exist in the same MR.

Example pair:
- `CreateRealVendorContractCommandHandler.cs`
- `CreateRealVendorContractCommandValidator.cs`

Validator must inherit `AbstractValidator<TCommand>` and validate input with `RuleFor(...)` (e.g. `NotEmpty().WithMessage(...)`).

#### RR-014 [WARNING] — No trailing blank line
A `.cs` file must not contain trailing blank lines after the final closing brace. The last line of the file must be `}`.

Detection: diff adds `\n` after final `}` or file ends with blank line.

### Logging

#### RR-015 [WARNING] — Handler entry/exit logging
Public handlers (Commands/Queries) in Application/Infrastructure must:
- Log at **method start** (`LogInformation("Handle started for ...")` or equivalent).
- Log **before each return** path (`LogInformation("Handle completed ...")` / `LogWarning` when applicable).
- Use structured placeholders (`{VendorCode}`, not string concat).

Domain layer is **exempt** — see RR-016.

#### RR-016 [ERROR] — Domain purity (no logging, no packages)
`Dizi.AppCore.Domain` (and subfolders) must **not**:
- Use `ILogger`, `Microsoft.Extensions.Logging`, or any logging call.
- Reference NuGet packages or project references beyond BCL / allowed domain primitives.
- Contain `using` to Infrastructure, Application, Endpoints, EF, HTTP clients, etc.

Detection patterns:
```regex
namespace\\s+Dizi\\.AppCore\\.Domain[\\s\\S]*?(ILogger|LogInformation|LogWarning|LogError|Microsoft\\.Extensions\\.Logging)
```

Domain `.csproj` must not list PackageReference entries (except whitelisted BCL-only if any).
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
- Review Skill (`review_skill`): Cursor SKILL.md for workspace-based Sentinel reviews; materialized to `.cursor/skills/sentinel-review/`.
- Agent Documents (`agent_documents`): governance and collection ownership; never injected into a review prompt.
- Architecture Specs (`architecture_spec`), ADR (`adr`), and Ubiquitous Language (`ubiquitous_language`): optional domain context.

All active content is stored, edited, and read from ChromaDB. Physical markdown files are not runtime sources.
"""

_RULE_LINE = re.compile(r"^- RR-(\d+) \[(\w+)\] (.+)$", re.MULTILINE)
_SKILL_RULE_HEADING = re.compile(r"^#{3,4} RR-(\d+) \[", re.MULTILINE)


def sync_review_skill_from_rules(review_rules: str, skill_body: str) -> tuple[str, list[str]]:
    """Append Review Rules entries that are missing from Review Skill (by RR id)."""
    rules_text = (review_rules or "").strip()
    skill_text = (skill_body or "").strip()
    if not rules_text or not skill_text:
        return skill_text, []

    present = set(_SKILL_RULE_HEADING.findall(skill_text))
    additions: list[str] = []
    added_ids: list[str] = []

    for rule_id, severity, description in _RULE_LINE.findall(rules_text):
        if rule_id in present:
            continue
        heading = description.split(".")[0].strip() or description.strip()
        additions.append(
            f"\n#### RR-{rule_id} [{severity}] — {heading}\n{description.strip()}\n"
        )
        added_ids.append(f"RR-{rule_id}")
        present.add(rule_id)

    if not additions:
        return skill_text, []

    marker = "### File layout & CQRS conventions"
    if marker in skill_text:
        idx = skill_text.find("### Logging")
        if idx == -1:
            updated = skill_text.rstrip() + "\n" + "".join(additions)
        else:
            updated = skill_text[:idx] + "".join(additions) + skill_text[idx:]
    else:
        updated = skill_text.rstrip() + "\n\n## Synced rules\n" + "".join(additions)

    return updated, added_ids


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
    "review-skill": (
        KnowledgeCollection.REVIEW_SKILL.value,
        "sentinel-review-skill",
        "Sentinel Review Skill",
        _DEFAULT_REVIEW_SKILL,
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
        if kind == "review-skill":
            self.validate_review_skill(text)
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
        synced_rule_ids: list[str] = []
        if kind == "review-rules" and stable_id == default_id:
            synced_rule_ids = self._sync_skill_after_rules_save(text)
        return {
            "id": stable_id,
            "kind": kind,
            "collection": collection,
            "title": (title or default_title).strip(),
            "content": text,
            "chunks_created": result["chunks_created"],
            "source": "chroma",
            "applied": True,
            "synced_skill_rule_ids": synced_rule_ids,
        }

    def delete_managed_document(self, kind: str, doc_id: str) -> int:
        collection, default_id, _title, _content = self._kind_config(kind)
        detail = self._store.get_document(doc_id)
        if not detail or detail.get("collection") != collection:
            return 0
        if doc_id == default_id and kind in {
            "review-prompt",
            "review-skill",
            "agent-documents",
        }:
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

    def get_review_skill(self) -> dict[str, Any]:
        _collection, doc_id, _title, _content = self._kind_config("review-skill")
        detail = self._store.get_document(doc_id)
        if not detail:
            self.ensure_defaults()
            detail = self._store.get_document(doc_id)
        if not detail:
            raise RuntimeError("Active review skill is missing from ChromaDB")
        return {
            "id": doc_id,
            "name": "sentinel-review",
            "body": str(detail.get("content") or "").strip(),
            "source": "chroma",
            "collection": KnowledgeCollection.REVIEW_SKILL.value,
            "editable": True,
        }

    def save_review_skill(self, body: str) -> dict[str, Any]:
        saved = self.upsert_managed_document("review-skill", content=body)
        return {
            "id": saved["id"],
            "name": "sentinel-review",
            "body": saved["content"],
            "source": "chroma",
            "collection": saved["collection"],
            "saved": True,
            "applied": True,
        }

    def sync_review_skill_from_active_rules(self) -> dict[str, Any]:
        """Copy missing RR-xxx entries from active Review Rules into Review Skill."""
        rules_doc = self._store.get_document("sentinel-review-rules")
        if not rules_doc:
            self.ensure_defaults()
            rules_doc = self._store.get_document("sentinel-review-rules")
        if not rules_doc:
            raise RuntimeError("Active review rules document not found in ChromaDB")

        skill = self.get_review_skill()
        updated_body, added_ids = sync_review_skill_from_rules(
            str(rules_doc.get("content") or ""),
            skill["body"],
        )
        if not added_ids:
            return {
                "synced": False,
                "added_rule_ids": [],
                "message": "Review Skill already contains all Review Rules entries.",
            }

        saved = self.save_review_skill(updated_body)
        return {
            "synced": True,
            "added_rule_ids": added_ids,
            "message": f"Added {len(added_ids)} rule(s) to Review Skill: {', '.join(added_ids)}",
            "body": saved["body"],
        }

    def _sync_skill_after_rules_save(self, review_rules: str) -> list[str]:
        try:
            skill = self.get_review_skill()
            updated_body, added_ids = sync_review_skill_from_rules(review_rules, skill["body"])
            if not added_ids:
                return []
            self.save_review_skill(updated_body)
            return added_ids
        except Exception:
            return []

    @staticmethod
    def validate_review_skill(body: str) -> None:
        text = (body or "").strip()
        if not text.startswith("---"):
            raise ValueError("Review skill must start with YAML frontmatter (---)")
        end = text.find("\n---", 3)
        if end == -1:
            raise ValueError("Review skill frontmatter must close with ---")
        frontmatter = text[3:end]
        if not re.search(r"^name:\s*sentinel-review\s*$", frontmatter, re.MULTILINE):
            raise ValueError("Review skill frontmatter must include name: sentinel-review")
        if "RR-001" not in text:
            raise ValueError("Review skill body must include rule RR-001")

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
