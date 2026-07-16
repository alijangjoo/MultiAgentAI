import json
import re
from typing import Any

from shared.agent_executors.cursor_client import CursorBridgeError, cursor_bridge_review
from shared.agent_executors.models import AgentExecutorType
from shared.agent_executors.settings_store import get_agent_executor_settings
from shared.llm.factory import create_code_review_llm_for_provider
from shared.models.domain import AgentName, CodeReviewResult, MergeRequestInfo
from shared.persistence.repository import AgentRunRepository


def _parse_review_json(content: str) -> CodeReviewResult:
    json_match = re.search(r"\{{[\s\S]*\}}", content)
    if json_match:
        review_data = json.loads(json_match.group())
    else:
        review_data = {
            "approved": False,
            "summary": "Could not parse review output. Manual review required.",
            "findings": ["Automated review parsing failed"],
            "suggestions": ["Perform manual code review"],
        }
    return CodeReviewResult(
        approved=review_data.get("approved", False),
        summary=review_data.get("summary", ""),
        findings=review_data.get("findings", []),
        suggestions=review_data.get("suggestions", []),
    )


async def execute_review(
    *,
    run_id: str,
    task_key: str,
    branch_name: str,
    mr: MergeRequestInfo,
    development_summary: str,
    code_context: str,
    mr_changes: list[dict] | None,
    repo: AgentRunRepository,
) -> dict[str, Any]:
    settings_store = get_agent_executor_settings()
    executor = settings_store.sentinel_executor

    await repo.log_event_by_type(
        run_id,
        AgentName.SENTINEL,
        "executor_selected",
        f"Review executor: {executor}",
        {"executor": executor.value},
    )

    prompt = f"""You are Sentinel, an expert .NET 8 code reviewer.

Review this merge request for a DDD/CQRS codebase.

## MR: {mr.title}
Branch: {mr.source_branch} -> {mr.target_branch}

## Development Summary:
{development_summary}

## Code Context:
{code_context[:6000]}

Provide a structured review with:
1. approved (true/false) - approve if no critical issues
2. summary (2-3 sentences)
3. findings (list of issues found)
4. suggestions (list of improvements)

Return valid JSON with keys: approved, summary, findings, suggestions.
Be strict about: SOLID principles, CQRS separation, validation, error handling.
"""

    await repo.log_event_by_type(
        run_id,
        AgentName.SENTINEL,
        "review_started",
        f"Reviewing MR !{mr.iid} via {executor}",
    )

    if executor == AgentExecutorType.CURSOR:
        try:
            result = await cursor_bridge_review(
                run_id=run_id,
                task_key=task_key,
                branch_name=branch_name,
                mr_title=mr.title,
                prompt=prompt,
                mr_changes=mr_changes,
            )
            review_data = result.get("review") or result
            review = CodeReviewResult(
                approved=review_data.get("approved", False),
                summary=review_data.get("summary", ""),
                findings=review_data.get("findings", []),
                suggestions=review_data.get("suggestions", []),
            )
            await repo.log_event_by_type(
                run_id,
                AgentName.SENTINEL,
                "cursor_review_completed",
                f"Cursor review: {'approved' if review.approved else 'changes requested'}",
            )
            return {"review": review, "executor": executor.value}
        except CursorBridgeError as exc:
            await repo.log_event_by_type(
                run_id,
                AgentName.SENTINEL,
                "cursor_bridge_error",
                str(exc),
            )
            raise

    llm = create_code_review_llm_for_provider(executor.value)
    response = await llm.ainvoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    review = _parse_review_json(content)

    await repo.log_event_by_type(
        run_id,
        AgentName.SENTINEL,
        "review_completed",
        f"[{executor}] Review completed: {'approved' if review.approved else 'changes requested'}",
        {"findings_count": len(review.findings)},
    )
    return {"review": review, "executor": executor.value}
