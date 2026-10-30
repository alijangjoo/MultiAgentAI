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


def is_deploy_pipeline_ref(
    ref: str | None,
    *,
    stage_branch: str,
    production_branch: str,
) -> bool:
    """Stage tag, stage branch, or production branch (e.g. main) pipeline."""
    if not ref:
        return False
    text = ref.strip()
    if is_stg_version_tag(text):
        return True
    return text in {stage_branch.strip(), production_branch.strip()}


def deploy_target_branch_for_ref(
    ref: str | None,
    *,
    stage_branch: str,
    production_branch: str,
) -> str:
    if ref and ref.strip() == production_branch.strip():
        return production_branch.strip()
    return stage_branch.strip()


def _latest_jobs_by_name(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """GitLab returns retried jobs; keep the newest run per job name."""
    latest: dict[str, dict[str, Any]] = {}
    for job in jobs:
        name = (job.get("name") or "").strip() or f"job-{job.get('id')}"
        jid = int(job.get("id") or 0)
        prev = latest.get(name)
        if prev is None or jid > int(prev.get("id") or 0):
            latest[name] = job
    return list(latest.values())


def all_required_jobs_succeeded(
    jobs: list[dict[str, Any]],
    *,
    pipeline_status: str | None = None,
) -> bool:
    """
    True when the pipeline's latest job runs are complete enough for Deploy Request.
    Retries leave older failed/canceled rows — only the newest job per name counts.
    If GitLab reports pipeline status success, trust that when job rows are ambiguous.
    """
    if not jobs:
        return (pipeline_status or "").lower() == "success"

    ok_statuses = {"success", "skipped"}
    latest = _latest_jobs_by_name(jobs)
    has_success = False
    for job in latest:
        status = (job.get("status") or "").lower()
        if status == "success":
            has_success = True
        if status in ok_statuses:
            continue
        if status == "manual":
            continue
        if status == "failed" and job.get("allow_failure"):
            continue
        if status in ("failed", "canceled"):
            return False
        if status in ("running", "pending", "created", "waiting_for_resource"):
            return False
        if status not in ok_statuses | {"manual"}:
            return False

    if has_success:
        return True
    return (pipeline_status or "").lower() == "success"


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
    stage_branch: str | None = None,
    target_branch: str | None = None,
    sha: str | None,
    limit: int = 40,
) -> dict[str, Any] | None:
    """Best-effort match of merged MR (Stage/main/…) to pipeline SHA."""
    branch = (target_branch or stage_branch or "").strip()
    if not branch:
        return None
    try:
        try:
            mrs = await gitlab.list_merge_requests(
                state="merged",
                limit=limit,
                target_branch=branch,
            )
        except TypeError:
            mrs = await gitlab.list_merge_requests(state="merged", limit=limit)
            mrs = [m for m in mrs if m.get("target_branch") == branch]
    except Exception:
        return None

    if sha:
        for mr in mrs:
            if mr.get("merge_commit_sha") == sha or mr.get("sha") == sha:
                return mr
    return mrs[0] if mrs else None


async def list_stg_tag_pipelines(
    gitlab: Any,
    limit: int,
    *,
    status: str | None = "success",
) -> list[dict[str, Any]]:
    """Recent Stage release tag pipelines (newest first)."""
    try:
        kwargs: dict[str, Any] = {"limit": limit, "scope": "tags"}
        if status:
            kwargs["status"] = status
        pipes = await gitlab.list_pipelines(**kwargs)
    except TypeError:
        if status:
            pipes = await gitlab.list_pipelines(status=status, limit=max(limit, 50))
        else:
            pipes = await gitlab.list_pipelines(limit=max(limit, 50))

    stg = [p for p in pipes if is_stg_version_tag(p.get("ref"))]
    stg.sort(key=lambda p: int(p.get("id") or 0), reverse=True)
    return stg


async def list_deploy_pipelines(
    gitlab: Any,
    limit: int,
    *,
    stage_branch: str,
    production_branch: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Stage tags + pipelines on stage and production (main) branches."""
    limit = max(1, limit)
    seen: set[int] = set()
    combined: list[dict[str, Any]] = []

    def _take(pipes: list[dict[str, Any]], *, ref_ok) -> None:
        for pipe in pipes:
            pid = pipe.get("id")
            if pid is None:
                continue
            pid_i = int(pid)
            if pid_i in seen:
                continue
            ref = pipe.get("ref")
            if not ref_ok(ref):
                continue
            seen.add(pid_i)
            combined.append(pipe)

    tag_pipes = await list_stg_tag_pipelines(gitlab, limit * 2, status=status)
    _take(tag_pipes, ref_ok=lambda r: is_stg_version_tag(r))

    for branch_ref in (production_branch.strip(), stage_branch.strip()):
        try:
            kwargs: dict[str, Any] = {"ref": branch_ref, "limit": limit}
            if status:
                kwargs["status"] = status
            branch_pipes = await gitlab.list_pipelines(**kwargs)
        except TypeError:
            if status:
                branch_pipes = await gitlab.list_pipelines(
                    ref=branch_ref, status=status, limit=limit
                )
            else:
                branch_pipes = await gitlab.list_pipelines(ref=branch_ref, limit=limit)
        except Exception:
            continue
        _take(branch_pipes, ref_ok=lambda r, br=branch_ref: (r or "").strip() == br)

    combined.sort(key=lambda p: int(p.get("id") or 0), reverse=True)
    return combined[:limit]


async def pipeline_fully_succeeded(
    gitlab: Any, pipeline_id: int
) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
    """Re-check pipeline status + jobs before registering."""
    detail: dict[str, Any] | None = None
    if hasattr(gitlab, "get_pipeline"):
        try:
            detail = await gitlab.get_pipeline(pipeline_id)
            if (detail.get("status") or "").lower() != "success":
                return False, [], detail
        except Exception:
            detail = None

    if not hasattr(gitlab, "list_pipeline_jobs"):
        return False, [], detail

    try:
        jobs = await gitlab.list_pipeline_jobs(pipeline_id)
    except Exception:
        return False, [], detail

    pipe_status = (detail.get("status") if detail else None) or None
    if not jobs:
        if pipe_status == "success":
            return True, [], detail
        return False, [], detail

    if all_required_jobs_succeeded(jobs, pipeline_status=pipe_status):
        return True, jobs, detail
    if pipe_status == "success":
        return True, jobs, detail
    return False, jobs, detail


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
