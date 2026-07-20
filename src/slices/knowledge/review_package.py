"""Assemble and validate the Knowledge Package required before Sentinel MR review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config import get_settings
from shared.integrations.factory import IntegrationContainer
from slices.knowledge.models.collections import KnowledgeCollection
from slices.knowledge.rag.vector_store import get_knowledge_store
from slices.knowledge.review_docs import get_review_docs_service


class KnowledgePackageError(Exception):
    """Raised when mandatory knowledge artifacts are missing for review."""

    def __init__(self, missing: list[str], details: str = ""):
        self.missing = missing
        msg = "Knowledge package incomplete. Missing: " + ", ".join(missing)
        if details:
            msg += f". {details}"
        super().__init__(msg)


@dataclass
class ReviewKnowledgePackage:
    task_key: str
    prd: str
    adrs: str
    code_specs: str
    architecture_specs: str
    source_context: str
    review_rules: str
    ubiquitous_language: str
    tech_stack: str
    missing_optional: list[str] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        return (
            f"## Task PRD\n{self.prd}\n\n"
            f"## Code Specs\n{self.code_specs}\n\n"
            f"## Architecture Specs\n{self.architecture_specs}\n\n"
            f"## ADRs\n{self.adrs}\n\n"
            f"## Codebase / Source Context\n{self.source_context}\n\n"
            f"## Ubiquitous Language\n{self.ubiquitous_language}\n\n"
            f"## Review Rules\n{self.review_rules}"
        )


def _collection_has_docs(collection: str, min_docs: int = 1) -> bool:
    store = get_knowledge_store()
    docs = store.list_documents(collection=collection, limit=min_docs + 5)
    return len(docs) >= min_docs


def _collection_text(collection: str, limit: int = 6000) -> str:
    return get_review_docs_service().load_collection_text(collection, limit)


def _tech_stack_label() -> str:
    settings = get_settings()
    version = settings.project_dotnet_version.strip() or "8"
    return (
        f".NET {version}, Onion + Vertical Slice, CQRS, DDD, FluentValidation, "
        "EF Core (Infrastructure only)"
    )


async def build_review_knowledge_package(
    *,
    task_key: str,
    integrations: IntegrationContainer,
    mr_changes: list[dict] | None = None,
    development_summary: str = "",
) -> ReviewKnowledgePackage:
    """Validate Chroma-backed knowledge and build the Sentinel review package."""
    missing: list[str] = []
    optional_missing: list[str] = []
    docs = get_review_docs_service()

    review_rules = _collection_text(KnowledgeCollection.REVIEW_RULES.value, 8000)
    if not review_rules or review_rules.strip() == "(none)":
        missing.append("review_rules (sync Review Rules in Knowledge Agent)")

    code_specs = _collection_text(KnowledgeCollection.CODE_SPECS.value, 6000)
    if not code_specs or code_specs.strip() == "(none)":
        missing.append("code_specs (sync Code Specs in Knowledge Agent)")

    adrs = _collection_text(KnowledgeCollection.ADR.value, 4000)
    # ADRs are optional for review — include when available, but never block.
    if not adrs or adrs.strip() == "(none)":
        optional_missing.append("adr")

    prd = ""
    if task_key:
        try:
            prd_content = await integrations.jira.get_prd_attachment_content(task_key)
            if prd_content and len(prd_content.strip()) > 40:
                prd = prd_content.strip()
            else:
                issue = await integrations.jira.get_issue(task_key)
                desc = (issue.get("description") or "").strip()
                summary = (issue.get("summary") or "").strip()
                prd = f"{summary}\n\n{desc}".strip()
        except Exception as exc:
            missing.append(f"prd for {task_key} (Jira: {exc})")

        if task_key and (not prd or len(prd) < 30):
            missing.append(f"prd for {task_key} (empty PRD/description in Jira)")
    else:
        missing.append("jira_task_key (use [VEN-123] in MR title or branch)")

    arch_specs = _collection_text(KnowledgeCollection.ARCHITECTURE_SPEC.value, 4000)
    if not arch_specs or arch_specs.strip() == "(none)":
        arch_specs = "(no architecture specs in Knowledge — optional)"

    ul = _collection_text(KnowledgeCollection.UBIQUITOUS_LANGUAGE.value, 3000)

    diff_text = docs.format_mr_diff(mr_changes)
    source_parts: list[str] = []
    if not diff_text or diff_text in {"(no changes)", "(no diff provided)"}:
        missing.append("mr_diff (GitLab returned no reviewable changes)")
    if _collection_has_docs(KnowledgeCollection.ARCHITECTURE_SPEC.value):
        source_parts.append(f"### Architecture specs (Knowledge)\n{arch_specs[:4000]}")
    if _collection_has_docs(KnowledgeCollection.CODE_PATTERNS.value):
        patterns = _collection_text(KnowledgeCollection.CODE_PATTERNS.value, 3000)
        source_parts.append(f"### Code patterns (Knowledge)\n{patterns}")
    if not source_parts:
        source_parts.append("(no additional codebase context in Knowledge)")

    source_context = "\n\n".join(source_parts)

    if missing:
        raise KnowledgePackageError(
            missing,
            "Complete missing items in Knowledge Agent / Jira, then retry Review.",
        )

    return ReviewKnowledgePackage(
        task_key=task_key,
        prd=prd,
        adrs=adrs if adrs and adrs != "(none)" else "(no ADRs found)",
        code_specs=code_specs,
        architecture_specs=arch_specs,
        source_context=source_context,
        review_rules=review_rules,
        ubiquitous_language=ul if ul and ul != "(none)" else "(none)",
        tech_stack=_tech_stack_label(),
        missing_optional=optional_missing,
    )
