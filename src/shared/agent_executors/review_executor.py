import json
import re
from typing import Any

from core.config import get_settings
from core.tracing import trace_config
from shared.agent_executors.cursor_client import CursorBridgeError, cursor_bridge_review
from shared.cursor_cli.context_builder import build_review_context
from shared.agent_executors.models import AgentExecutorType
from shared.agent_executors.settings_store import get_agent_executor_settings
from shared.llm.factory import create_code_review_llm_for_provider
from shared.models.domain import AgentName, CodeReviewResult, MergeRequestInfo
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.review_docs import get_review_docs_service
from slices.knowledge.review_package import ReviewKnowledgePackage


def _item_to_string(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        severity = str(item.get("severity") or item.get("level") or "").strip().upper()
        path = str(item.get("file") or item.get("path") or item.get("location") or "").strip()
        line = item.get("line")
        message = str(
            item.get("message")
            or item.get("description")
            or item.get("finding")
            or item.get("text")
            or item.get("suggestion")
            or ""
        ).strip()
        parts: list[str] = []
        if severity:
            parts.append(f"[{severity}]")
        if path:
            loc = f"{path}:{line}" if line not in (None, "", 0, "0") else path
            parts.append(loc)
        if message:
            parts.append(("- " if parts else "") + message)
        return " ".join(parts).strip() or json.dumps(item, ensure_ascii=False)
    return str(item).strip()


def _normalize_string_list(items: Any) -> list[str]:
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        return [text] if text else []
    if not isinstance(items, list):
        text = _item_to_string(items)
        return [text] if text else []
    return [text for text in (_item_to_string(item) for item in items) if text]


def _coerce_review_result(
    review_data: dict[str, Any] | None,
    *,
    fallback_summary: str = "",
) -> CodeReviewResult:
    data = review_data if isinstance(review_data, dict) else {}
    findings = _normalize_string_list(data.get("findings"))
    suggestions = _normalize_string_list(data.get("suggestions"))
    approved = data.get("approved")
    if approved is None:
        approved = not any(item.upper().startswith("[ERROR]") for item in findings)
    return CodeReviewResult(
        approved=bool(approved),
        summary=str(data.get("summary") or fallback_summary or "").strip(),
        findings=findings,
        suggestions=suggestions,
    )


def _parse_review_json(content: str) -> CodeReviewResult:
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            review_data = json.loads(json_match.group())
            if isinstance(review_data, dict):
                return _coerce_review_result(review_data, fallback_summary=content[:500])
        except json.JSONDecodeError:
            pass

    findings = re.findall(r"\[(?:ERROR|WARNING)\][^\n]+", content)
    suggestions = re.findall(r"\[SUGGESTION\][^\n]+", content)
    return _coerce_review_result(
        {
            "approved": not any(line.startswith("[ERROR]") for line in findings),
            "summary": "Parsed structured findings from review output.",
            "findings": findings or ["Automated review parsing failed"],
            "suggestions": suggestions or ["Perform manual code review"],
        }
    )


def _build_prompt(
    *,
    mr: MergeRequestInfo,
    task_key: str,
    development_summary: str,
    code_context: str,
    mr_changes: list[dict] | None,
    knowledge_package: ReviewKnowledgePackage | None = None,
) -> str:
    docs = get_review_docs_service()
    diff = docs.format_mr_diff(mr_changes)
    if not mr_changes and code_context and code_context.strip():
        diff = f"{diff}\n\n## Extra code context\n{code_context[:4000]}"

    if knowledge_package:
        return docs.render_review_prompt(
            mr_title=mr.title,
            source_branch=mr.source_branch,
            target_branch=mr.target_branch,
            development_summary=development_summary,
            jira_ticket=task_key or "(no task key)",
            prd=knowledge_package.prd,
            diff=diff,
            tech_stack=knowledge_package.tech_stack,
            adrs=knowledge_package.adrs,
            code_specs=knowledge_package.code_specs,
            architecture_specs=knowledge_package.architecture_specs,
            source_context=knowledge_package.source_context,
            ubiquitous_language=knowledge_package.ubiquitous_language,
            review_rules=knowledge_package.review_rules,
        )

    return docs.render_review_prompt(
        mr_title=mr.title,
        source_branch=mr.source_branch,
        target_branch=mr.target_branch,
        development_summary=development_summary,
        jira_ticket=f"{task_key}: {development_summary}".strip(": "),
        prd=development_summary,
        diff=diff,
        source_context=diff,
    )


def build_review_prompt(
    *,
    mr: MergeRequestInfo,
    task_key: str,
    development_summary: str,
    code_context: str,
    mr_changes: list[dict] | None,
    knowledge_package: ReviewKnowledgePackage | None = None,
) -> str:
    return _build_prompt(
        mr=mr,
        task_key=task_key,
        development_summary=development_summary,
        code_context=code_context,
        mr_changes=mr_changes,
        knowledge_package=knowledge_package,
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
    knowledge_package: ReviewKnowledgePackage | None = None,
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

    prompt = _build_prompt(
        mr=mr,
        task_key=task_key,
        development_summary=development_summary,
        code_context=code_context,
        mr_changes=mr_changes,
        knowledge_package=knowledge_package,
    )

    await repo.log_event_by_type(
        run_id,
        AgentName.SENTINEL,
        "review_started",
        f"Reviewing MR !{mr.iid} via {executor}",
        {"prompt_chars": len(prompt)},
    )

    if executor == AgentExecutorType.CURSOR:
        settings = get_settings()
        review_context = build_review_context(
            mr=mr,
            task_key=task_key,
            development_summary=development_summary,
            code_context=code_context,
            mr_changes=mr_changes,
            knowledge_package=knowledge_package,
            language=settings.cursor_review_language,
        )
        try:
            result = await cursor_bridge_review(
                run_id=run_id,
                task_key=task_key,
                branch_name=branch_name,
                context=review_context.model_dump(),
            )
            review_data = result.get("review") or result
            if isinstance(review_data, str):
                review = _parse_review_json(review_data)
            else:
                review = _coerce_review_result(
                    review_data if isinstance(review_data, dict) else {},
                    fallback_summary=str(review_data)[:500],
                )
            await repo.log_event_by_type(
                run_id,
                AgentName.SENTINEL,
                "cursor_review_completed",
                f"Cursor review: {'approved' if review.approved else 'changes requested'}",
            )
            return {"review": review, "executor": executor.value, "prompt": prompt}
        except CursorBridgeError as exc:
            await repo.log_event_by_type(
                run_id,
                AgentName.SENTINEL,
                "cursor_bridge_error",
                str(exc),
            )
            raise

    llm = create_code_review_llm_for_provider(executor.value)
    response = await llm.ainvoke(
        prompt,
        config=trace_config(
            run_id=run_id,
            agent_name="sentinel",
            workflow_type="code_review",
        ),
    )
    content = response.content if hasattr(response, "content") else str(response)
    review = _parse_review_json(content)

    await repo.log_event_by_type(
        run_id,
        AgentName.SENTINEL,
        "review_completed",
        f"[{executor}] Review completed: {'approved' if review.approved else 'changes requested'}",
        {"findings_count": len(review.findings)},
    )
    return {"review": review, "executor": executor.value, "prompt": prompt}
