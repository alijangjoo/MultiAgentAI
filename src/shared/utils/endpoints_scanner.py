"""Discover Dizi endpoint project names from the local repo."""

from __future__ import annotations

from pathlib import Path

from core.config import get_settings

_IGNORE_SUFFIXES = ("Base", "Observability")


def list_endpoint_projects(repo_path: str | None = None) -> list[str]:
    settings = get_settings()
    root = Path(repo_path or settings.dizi_repo_path)
    endpoints_dir = root / settings.dizi_src_relative / "Endpoints"
    if not endpoints_dir.is_dir():
        return []

    names: list[str] = []
    for child in sorted(endpoints_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _IGNORE_SUFFIXES:
            continue
        names.append(f"Dizi.Endpoints.{child.name}")
    return names
