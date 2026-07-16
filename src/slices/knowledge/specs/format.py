"""Unified Dizi architecture spec format (YAML frontmatter + Markdown body)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import yaml
from pydantic import BaseModel, Field


class SpecFrontmatter(BaseModel):
    spec_id: str
    spec_version: str = "1.0"
    title: str
    structure_tag: str = Field(description="new-structure | legacy-api")
    source_kind: str = Field(description="architecture | layer | pattern | bounded-context | feature")
    source_path: str = ""
    branch: str = "dev-oms-v2"
    bounded_context: str | None = None
    layers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    updated_at: str | None = None


class ArchitectureSpec(BaseModel):
    frontmatter: SpecFrontmatter
    body: str

    def to_markdown(self) -> str:
        fm = self.frontmatter.model_dump(exclude_none=True)
        yaml_block = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
        body = self.body.strip()
        return f"---\n{yaml_block}\n---\n\n{body}\n"

    @property
    def spec_id(self) -> str:
        return self.frontmatter.spec_id


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def parse_spec_markdown(text: str) -> ArchitectureSpec:
    match = FRONTMATTER_RE.match(text.strip())
    if not match:
        raise ValueError("Spec must start with YAML frontmatter (--- ... ---)")
    fm_raw, body = match.group(1), match.group(2)
    data = yaml.safe_load(fm_raw) or {}
    return ArchitectureSpec(frontmatter=SpecFrontmatter(**data), body=body.strip())


def build_spec(
    *,
    spec_id: str,
    title: str,
    structure_tag: str,
    source_kind: str,
    source_path: str,
    branch: str,
    body: str,
    bounded_context: str | None = None,
    layers: list[str] | None = None,
    extra_tags: list[str] | None = None,
) -> ArchitectureSpec:
    now = datetime.now(timezone.utc).isoformat()
    tags = ["dizi-spec", structure_tag]
    if extra_tags:
        tags.extend(extra_tags)
    tags = list(dict.fromkeys(tags))

    return ArchitectureSpec(
        frontmatter=SpecFrontmatter(
            spec_id=spec_id,
            title=title,
            structure_tag=structure_tag,
            source_kind=source_kind,
            source_path=source_path,
            branch=branch,
            bounded_context=bounded_context,
            layers=layers or [],
            tags=tags,
            generated_at=now,
            updated_at=now,
        ),
        body=body,
    )


def spec_tags_for_ingest(spec: ArchitectureSpec) -> list[str]:
    return list(spec.frontmatter.tags)
