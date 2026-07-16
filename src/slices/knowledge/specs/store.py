"""File-backed store for architecture specs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.config import get_settings
from slices.knowledge.specs.format import ArchitectureSpec, parse_spec_markdown


class SpecFileStore:
    def __init__(self, storage_path: str | None = None):
        settings = get_settings()
        raw = storage_path or settings.dizi_specs_storage_path
        path = Path(raw)
        if not path.is_absolute():
            root = Path(__file__).resolve().parents[4]
            path = root / raw
        self._root = path
        self._root.mkdir(parents=True, exist_ok=True)

    def _file_for(self, spec_id: str) -> Path:
        safe = spec_id.replace("/", "__")
        return self._root / f"{safe}.md"

    def save(self, spec: ArchitectureSpec) -> Path:
        path = self._file_for(spec.spec_id)
        path.write_text(spec.to_markdown(), encoding="utf-8")
        return path

    def save_many(self, specs: list[ArchitectureSpec]) -> list[Path]:
        return [self.save(s) for s in specs]

    def load(self, spec_id: str) -> ArchitectureSpec | None:
        path = self._file_for(spec_id)
        if not path.exists():
            return None
        return parse_spec_markdown(path.read_text(encoding="utf-8"))

    def update_body(self, spec_id: str, body: str, updated_by: str = "dashboard") -> ArchitectureSpec:
        spec = self.load(spec_id)
        if not spec:
            raise FileNotFoundError(f"Spec not found: {spec_id}")
        spec.body = body
        spec.frontmatter.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(spec)
        return spec

    def list_specs(
        self,
        structure_tag: str | None = None,
    ) -> list[dict]:
        items: list[dict] = []
        for path in sorted(self._root.glob("*.md")):
            try:
                spec = parse_spec_markdown(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if structure_tag and spec.frontmatter.structure_tag != structure_tag:
                continue
            items.append(
                {
                    "spec_id": spec.spec_id,
                    "title": spec.frontmatter.title,
                    "structure_tag": spec.frontmatter.structure_tag,
                    "source_kind": spec.frontmatter.source_kind,
                    "source_path": spec.frontmatter.source_path,
                    "bounded_context": spec.frontmatter.bounded_context,
                    "tags": spec.frontmatter.tags,
                    "updated_at": spec.frontmatter.updated_at,
                    "file_path": str(path),
                }
            )
        return items

    def load_all(self) -> list[ArchitectureSpec]:
        specs: list[ArchitectureSpec] = []
        for path in sorted(self._root.glob("*.md")):
            try:
                specs.append(parse_spec_markdown(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return specs

    def read_raw(self, spec_id: str) -> str:
        path = self._file_for(spec_id)
        if not path.exists():
            raise FileNotFoundError(spec_id)
        return path.read_text(encoding="utf-8")
