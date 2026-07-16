"""Orchestrate spec scan, file storage, and Knowledge Agent (Chroma) sync."""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings
from shared.models.domain import AgentName, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.models.collections import KnowledgeCollection
from slices.knowledge.rag.vector_store import get_knowledge_store
from slices.knowledge.specs.format import ArchitectureSpec, spec_tags_for_ingest
from slices.knowledge.specs.scanner import scan_dizi_repository
from slices.knowledge.specs.store import SpecFileStore


class ArchitectureSpecService:
    COLLECTION = KnowledgeCollection.ARCHITECTURE_SPEC.value

    def __init__(
        self,
        store: SpecFileStore | None = None,
        run_repo: AgentRunRepository | None = None,
    ):
        self._file_store = store or SpecFileStore()
        self._vector = get_knowledge_store()
        self._run_repo = run_repo or AgentRunRepository()
        self._settings = get_settings()

    def list_specs(self, structure_tag: str | None = None) -> list[dict]:
        return self._file_store.list_specs(structure_tag=structure_tag)

    def get_spec(self, spec_id: str) -> dict:
        spec = self._file_store.load(spec_id)
        if not spec:
            raise FileNotFoundError(spec_id)
        return {
            "spec_id": spec.spec_id,
            "frontmatter": spec.frontmatter.model_dump(),
            "body": spec.body,
            "markdown": spec.to_markdown(),
        }

    def update_spec(self, spec_id: str, body: str, sync_knowledge: bool = True) -> dict:
        spec = self._file_store.update_body(spec_id, body)
        if sync_knowledge:
            self._ingest_one(spec)
        return self.get_spec(spec_id)

    async def scan_from_source(
        self,
        repo_path: str | None = None,
        branch: str | None = None,
        sync_knowledge: bool = True,
    ) -> dict:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.KNOWLEDGE_INGEST.value,
            agent_name=AgentName.SAGE,
            input_payload={
                "action": "spec_scan",
                "repo_path": repo_path or self._settings.dizi_repo_path,
                "branch": branch or self._settings.dizi_spec_branch,
            },
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        root = Path(repo_path or self._settings.dizi_repo_path)
        if not root.exists():
            msg = f"Repository path not found: {root}"
            await self._run_repo.update_run(run_id, status=RunStatus.FAILED, error_message=msg)
            raise FileNotFoundError(msg)

        specs = scan_dizi_repository(repo_path=root, branch=branch)
        self._file_store.save_many(specs)

        synced = 0
        if sync_knowledge:
            synced = self.sync_all_to_knowledge()

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload={
                "specs_generated": len(specs),
                "specs_synced": synced,
                "new_structure": sum(1 for s in specs if s.frontmatter.structure_tag == "new-structure"),
                "legacy_api": sum(1 for s in specs if s.frontmatter.structure_tag == "legacy-api"),
            },
        )
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.SAGE,
            "spec_scan_completed",
            f"Generated {len(specs)} specs, synced {synced} to knowledge",
        )

        return {
            "run_id": run_id,
            "specs_generated": len(specs),
            "specs_synced": synced,
            "spec_ids": [s.spec_id for s in specs],
            "message": f"Scanned {root} — {len(specs)} specs saved",
        }

    def sync_all_to_knowledge(self) -> int:
        specs = self._file_store.load_all()
        for spec in specs:
            self._ingest_one(spec)
        return len(specs)

    def _ingest_one(self, spec: ArchitectureSpec) -> None:
        self._vector.delete_document(spec.spec_id)
        self._vector.ingest(
            collection=self.COLLECTION,
            title=spec.frontmatter.title,
            content=spec.to_markdown(),
            tags=spec_tags_for_ingest(spec),
            source=f"spec:{spec.spec_id}",
            doc_id=spec.spec_id,
        )

    def get_template_path(self) -> Path:
        root = Path(__file__).resolve().parents[4]
        return root / "docs" / "specs" / "SPEC_TEMPLATE.md"
