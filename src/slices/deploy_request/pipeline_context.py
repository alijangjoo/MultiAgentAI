"""Helpers to resolve Deploy Request context from a successful Stage pipeline."""

from __future__ import annotations

import re
from typing import Any

from core.config import get_settings
from shared.utils.jira_key_from_branch import extract_jira_key_from_branch

_VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:-[\w.]+)?", re.IGNORECASE)
# Tag pipelines for Stage deploy, e.g. v2.307.0-stg
_STG_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[\w.]*)?-?stg$", re.IGNORECASE)


def is_stg_version_tag(ref: str | None) -> bool:
    """True when pipeline ref is a Stage release tag (e.g. v2.307.0-stg)."""
    if not ref:
        return False
    text = ref.strip()
    if _STG_TAG_RE.match(text):
        return True
    # Also accept tags that contain -stg after a semver, e.g. v2.307.0-stg
    if "-stg" in text.lower() and _VERSION_RE.search(text):
        return True
    return False


def normalize_version_tag(ref: str | None) -> str | None:
    """Return canonical version string from a pipeline tag/ref."""
    if not ref:
        return None
    text = ref.strip()
    if _VERSION_RE.fullmatch(text) or is_stg_version_tag(text):
        return text if text.startswith("v") or not text[0].isdigit() else f"v{text}"
    match = _VERSION_RE.search(text)
    if not match:
        return None
    ver = match.group(0)
    return ver if ver.startswith("v") else f"v{ver}"


def all_required_jobs_succeeded(jobs: list[dict[str, Any]]) -> bool:
    """
    True only when every pipeline stage/job has fully finished:
    - every job is success or skipped (not failed, manual, pending, running, …)
    - allow_failure failures still count as incomplete for Deploy Request
    """
    if not jobs:
        return False
    ok_statuses = {"success", "skipped"}
    for job in jobs:
        status = (job.get("status") or "").lower()
        if status not in ok_statuses:
            return False
    return any((j.get("status") or "").lower() == "success" for j in jobs)


def is_ready_list_status(status: str | None) -> bool:
    """Statuses shown in Ready / In progress (success pipelines not yet Published)."""
    return (status or "") in {
        "pipeline_ready",
        "draft",
        "waiting_approval",
        "needs_jira",
    }


def commit_changes_url(
    sha: str | None,
    pipeline_url: str | None = None,
    mr_url: str | None = None,
) -> str | None:
    """Build GitLab commit URL used as Changes link."""
    if not sha:
        return None
    for url in (pipeline_url, mr_url):
        if url and "/-/" in url:
            base = url.split("/-/")[0].rstrip("/")
            return f"{base}/-/commit/{sha}"
    settings = get_settings()
    base = (settings.gitlab_url or "").rstrip("/")
    path = (settings.gitlab_project_path or "").strip("/")
    if not base or not path:
        return None
    return f"{base}/{path}/-/commit/{sha}"


def extract_version_from_jobs(jobs: list[dict[str, Any]], ref: str | None = None) -> str | None:
    # Prefer pipeline tag/ref (e.g. v2.307.0-stg on GitLab "For v2.307.0-stg")
    from_ref = normalize_version_tag(ref)
    if from_ref:
        return from_ref
    for job in jobs:
        name = job.get("name") or ""
        if "bump" in name.lower() or "version" in name.lower() or "tag" in name.lower():
            match = _VERSION_RE.search(name)
            if match:
                ver = match.group(0)
                return ver if ver.startswith("v") else f"v{ver}"
    for job in jobs:
        match = _VERSION_RE.search(job.get("name") or "")
        if match:
            ver = match.group(0)
            return ver if ver.startswith("v") else f"v{ver}"
    return None


async def find_related_merged_mr(
    gitlab: Any,
    *,
    stage_branch: str,
    sha: str | None,
    limit: int = 40,
) -> dict[str, Any] | None:
    """Best-effort match of merged Stage MR to pipeline SHA."""
    try:
        try:
            mrs = await gitlab.list_merge_requests(
                state="merged",
                limit=limit,
                target_branch=stage_branch,
            )
        except TypeError:
            mrs = await gitlab.list_merge_requests(state="merged", limit=limit)
            mrs = [m for m in mrs if m.get("target_branch") == stage_branch]
    except Exception:
        return None

    if sha:
        for mr in mrs:
            if mr.get("merge_commit_sha") == sha or mr.get("sha") == sha:
                return mr
    # Fallback: newest merged Stage MR (often the one that triggered bump)
    return mrs[0] if mrs else None


def context_from_mr(mr: dict[str, Any] | None) -> dict[str, Any]:
    if not mr:
        return {
            "mr_iid": None,
            "mr_url": None,
            "source_branch": None,
            "jira_key": None,
        }
    source = mr.get("source_branch") or ""
    return {
        "mr_iid": mr.get("iid"),
        "mr_url": mr.get("web_url"),
        "source_branch": source or None,
        "jira_key": extract_jira_key_from_branch(source),
    }
