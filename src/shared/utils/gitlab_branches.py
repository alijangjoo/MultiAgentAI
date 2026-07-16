"""Normalize GitLab branch lists with pinned environment branches."""

from __future__ import annotations

from core.config import Settings, get_settings


def pinned_branch_names(settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    candidates = [
        s.gitlab_feature_source_branch,
        "main",
        "master",
        s.gitlab_mr_target_dev,
        s.gitlab_mr_target_stage,
        s.gitlab_mr_target_production,
        s.gitlab_default_branch,
        s.dizi_spec_branch,
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in candidates:
        if name and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def normalize_branch_list(
    remote_branches: list[str],
    *,
    settings: Settings | None = None,
    limit: int | None = None,
) -> list[str]:
    s = settings or get_settings()
    pinned = pinned_branch_names(s)
    seen = set(pinned)
    merged = list(pinned)

    for branch in sorted(remote_branches, key=str.lower):
        if branch not in seen:
            merged.append(branch)
            seen.add(branch)

    if limit and len(merged) > limit:
        head = [b for b in merged if b in pinned]
        tail = [b for b in merged if b not in pinned][: max(0, limit - len(head))]
        return head + tail

    return merged
