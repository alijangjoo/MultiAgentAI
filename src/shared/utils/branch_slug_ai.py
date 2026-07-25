"""AI-assisted short branch slug generation from Jira task content."""

from __future__ import annotations

import re

from core.tracing import trace_config
from shared.llm.factory import create_llm
from shared.utils.branch_naming import build_feature_branch_name, slugify


async def suggest_branch_slug(
    *,
    task_key: str,
    summary: str,
    description: str = "",
    prd_preview: str | None = None,
) -> dict[str, str]:
    """Return a very short kebab-case slug and full feature branch name."""
    fallback = _fallback_slug(summary)

    prompt = f"""You name Git feature branches for a .NET team.

Task key: {task_key}
Summary: {summary}
Description:
{(description or '')[:800]}

{(f'PRD excerpt:{prd_preview[:600]}' if prd_preview else '')}

Rules:
- Output ONLY a short slug: 2-5 English words, kebab-case
- Max 35 characters, lowercase, no task key, no "feature/" prefix
- Capture the essence of the work (e.g. create-api-for-contract, add-redis-cache)

Slug:"""

    try:
        llm = create_llm(temperature=0)
        response = await llm.ainvoke(
            prompt,
            config=trace_config(agent_name="branch_slug", workflow_type="branch_naming"),
        )
        raw = response.content if hasattr(response, "content") else str(response)
        slug = _clean_slug(raw)
        if len(slug) < 3:
            slug = fallback
    except Exception:
        slug = fallback

    return {
        "short_description": slug,
        "branch_name": build_feature_branch_name(task_key, summary, slug),
    }


def _clean_slug(text: str) -> str:
    line = text.strip().splitlines()[0].strip().strip('"').strip("'")
    line = re.sub(r"^(slug|branch)\s*:\s*", "", line, flags=re.I)
    return slugify(line, max_length=35)


def _fallback_slug(summary: str) -> str:
    words = slugify(summary, max_length=35).split("-")
    return "-".join(words[:5]) if words else "feature-work"
