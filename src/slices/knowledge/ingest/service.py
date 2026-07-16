"""Bulk knowledge ingestion from GitLab, Confluence, local docs, and merged MRs."""

from pathlib import Path
from typing import Any

from core.config import get_settings
from shared.integrations.registry import get_integrations
from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.models.collections import KnowledgeCollection
from slices.knowledge.rag.vector_store import get_knowledge_store


def _classify_gitlab_path(path: str) -> str:
    lower = path.lower()
    if "/adr/" in lower or lower.startswith("docs/adr"):
        return KnowledgeCollection.ADR.value
    if "/ul/" in lower or "api" in lower:
        return KnowledgeCollection.API_REFERENCE.value
    if lower.endswith(".cs"):
        return KnowledgeCollection.CODE_PATTERNS.value
    return KnowledgeCollection.BEST_PRACTICES.value


class KnowledgeIngestService:
    def __init__(self, run_repo: AgentRunRepository | None = None):
        self._integrations = get_integrations()
        self._store = get_knowledge_store()
        self._run_repo = run_repo or AgentRunRepository()
        self._settings = get_settings()

    async def ingest_gitlab(
        self,
        ref: str | None = None,
        path: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.KNOWLEDGE_INGEST.value,
            agent_name=AgentName.SAGE,
            input_payload={"source": "gitlab", "ref": ref, "path": path},
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        files = await self._integrations.gitlab.list_repository_files(
            ref=ref,
            path=path,
            extensions=[".cs", ".md", ".json"],
            limit=limit,
        )
        base_ref = ref or self._settings.gitlab_default_branch
        docs = 0
        chunks = 0

        for item in files:
            file_path = item["path"]
            try:
                content = await self._integrations.gitlab.get_file_content(file_path, base_ref)
            except Exception:
                continue
            if len(content.strip()) < 20:
                continue
            collection = _classify_gitlab_path(file_path)
            result = self._store.ingest(
                collection=collection,
                title=file_path,
                content=content,
                tags=["gitlab", collection],
                source=f"gitlab:{file_path}@{base_ref}",
            )
            docs += 1
            chunks += result["chunks_created"]

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload={"documents_ingested": docs, "chunks_created": chunks},
        )
        return {
            "source": "gitlab",
            "documents_ingested": docs,
            "chunks_created": chunks,
            "run_id": run_id,
        }

    async def ingest_confluence(
        self,
        query: str = "API",
        space_key: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.KNOWLEDGE_INGEST.value,
            agent_name=AgentName.SAGE,
            input_payload={"source": "confluence", "query": query},
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        space = space_key or self._settings.confluence_space_key
        pages = await self._integrations.confluence.search_pages(query=query, space_key=space)
        docs = 0
        chunks = 0

        for page in pages[:limit]:
            page_id = str(page.get("id") or page.get("content", {}).get("id", ""))
            if not page_id:
                continue
            try:
                full = await self._integrations.confluence.get_page_content(page_id)
            except Exception:
                continue
            content = full.get("content", "")
            if len(content.strip()) < 20:
                continue
            result = self._store.ingest(
                collection=KnowledgeCollection.HISTORICAL_CONTEXT.value,
                title=full.get("title", page_id),
                content=content,
                tags=["confluence", space or ""],
                source=f"confluence:{page_id}",
            )
            docs += 1
            chunks += result["chunks_created"]

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload={"documents_ingested": docs, "chunks_created": chunks},
        )
        return {
            "source": "confluence",
            "documents_ingested": docs,
            "chunks_created": chunks,
            "run_id": run_id,
        }

    async def ingest_local_docs(self, docs_root: str | None = None) -> dict[str, Any]:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.KNOWLEDGE_INGEST.value,
            agent_name=AgentName.SAGE,
            input_payload={"source": "local"},
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        root = Path(docs_root) if docs_root else Path(__file__).resolve().parents[3].parent / "docs"
        docs = 0
        chunks = 0

        if root.exists():
            for md_file in root.rglob("*.md"):
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                if len(content.strip()) < 20:
                    continue
                rel = str(md_file.relative_to(root))
                collection = (
                    KnowledgeCollection.ADR.value
                    if "adr" in rel.lower()
                    else KnowledgeCollection.BEST_PRACTICES.value
                )
                result = self._store.ingest(
                    collection=collection,
                    title=rel,
                    content=content,
                    tags=["local", collection],
                    source=f"local:{rel}",
                )
                docs += 1
                chunks += result["chunks_created"]

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload={"documents_ingested": docs, "chunks_created": chunks},
        )
        return {
            "source": "local",
            "documents_ingested": docs,
            "chunks_created": chunks,
            "run_id": run_id,
        }

    async def ingest_merge_request(self, mr_iid: int) -> dict[str, Any]:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.KNOWLEDGE_INGEST.value,
            agent_name=AgentName.SAGE,
            input_payload={"source": "merge_request", "mr_iid": mr_iid},
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        mr = await self._integrations.gitlab.get_merge_request(mr_iid)
        changes = await self._integrations.gitlab.get_merge_request_changes(mr_iid)
        docs = 0
        chunks = 0

        summary_parts = [
            f"# MR !{mr_iid}: {mr.get('title', '')}",
            f"Branch: {mr.get('source_branch')} -> {mr.get('target_branch')}",
            mr.get("description") or "",
        ]
        for change in changes:
            summary_parts.append(
                f"\n## {change.get('new_path')}\n```diff\n{change.get('diff', '')[:3000]}\n```"
            )
        content = "\n".join(summary_parts)
        result = self._store.ingest(
            collection=KnowledgeCollection.SOLUTIONS.value,
            title=f"MR !{mr_iid} - {mr.get('title', '')}",
            content=content,
            tags=["merge_request", f"mr-{mr_iid}"],
            source=f"gitlab:mr:{mr_iid}",
        )
        docs += 1
        chunks += result["chunks_created"]

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload={"documents_ingested": docs, "chunks_created": chunks},
        )
        return {
            "source": f"mr-{mr_iid}",
            "documents_ingested": docs,
            "chunks_created": chunks,
            "run_id": run_id,
        }
