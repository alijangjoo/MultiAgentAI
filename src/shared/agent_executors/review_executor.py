import json
import re
from typing import Any

from core.config import get_settings
from core.tracing import trace_config
from shared.agent_executors.cursor_client import CursorBridgeError, cursor_bridge_review
from shared.cursor_cli.context_builder import build_review_context
from shared.cursor_cli.review_workspace import (
    ReviewWorkspaceError,
    ReviewWorkspaceSession,
    review_workspace_enabled,
)
from shared.review.progress import ReviewProgressReporter
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
    progress: ReviewProgressReporter | None = None,
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
        if progress:
            await progress.log("build_context", "Building ReviewContext + skill prompt")
        review_context = build_review_context(
            mr=mr,
            task_key=task_key,
            development_summary=development_summary,
            code_context=code_context,
            mr_changes=mr_changes,
            knowledge_package=knowledge_package,
            language=settings.cursor_review_language,
        )
        skill_prompt = prompt

        try:
            if review_workspace_enabled():
                if progress:
                    await progress.log(
                        "worktree",
                        f"Creating git worktree for branch {branch_name}",
                    )
                try:
                    async with ReviewWorkspaceSession(
                        repo_path=settings.cursor_repo_path,
                        branch_name=branch_name,
                        mr_iid=mr.iid,
                        run_id=run_id,
                        progress=progress,
                    ) as workspace:
                        if progress:
                            await progress.log(
                                "skill",
                                f"Skill materialized at {workspace.skill_path}",
                                skill_path=str(workspace.skill_path),
                            )
                        skill_context = review_context.model_copy(
                            update={"use_review_skill": True}
                        )
                        from shared.cursor_cli.prompt_builder import (
                            build_review_prompt as build_cli_review_prompt,
                        )

                        skill_prompt = build_cli_review_prompt(
                            skill_context,
                            output_format=settings.cursor_cli_review_output_format,
                        )
                        if progress:
                            await progress.log(
                                "prompt",
                                f"Prompt ready ({len(skill_prompt)} chars, JSON + sentinel-review skill)",
                                workspace=str(workspace.path),
                            )
                        await repo.log_event_by_type(
                            run_id,
                            AgentName.SENTINEL,
                            "review_workspace_created",
                            f"Worktree at {workspace.path} with skill {workspace.skill_path.name}",
                            {
                                "workspace": str(workspace.path),
                                "skill_path": str(workspace.skill_path),
                                "branch": branch_name,
                            },
                        )
                        if progress:
                            await progress.log(
                                "cursor_bridge",
                                "Calling Cursor Bridge → agent subprocess (--workspace, --mode agent)",
                                workspace=str(workspace.path),
                            )
                        result = await cursor_bridge_review(
                            run_id=run_id,
                            task_key=task_key,
                            branch_name=branch_name,
                            context=skill_context.model_dump(),
                            workspace=str(workspace.path),
                        )
                        if progress:
                            backend = result.get("backend") or "cursor-cli"
                            await progress.log(
                                "cursor_cli",
                                f"Cursor CLI finished (backend: {backend})",
                            )
                except ReviewWorkspaceError as exc:
                    await repo.log_event_by_type(
                        run_id,
                        AgentName.SENTINEL,
                        "review_workspace_failed",
                        str(exc),
                    )
                    raise CursorBridgeError(
                        f"Review workspace setup failed: {exc}. "
                        f"Check CURSOR_REPO_PATH and that origin/{branch_name} exists."
                    ) from exc
            else:
                if progress:
                    await progress.log(
                        "cursor_bridge",
                        "Calling Cursor Bridge (inline prompt, no worktree)",
                    )
                result = await cursor_bridge_review(
                    run_id=run_id,
                    task_key=task_key,
                    branch_name=branch_name,
                    context=review_context.model_dump(),
                )
        except CursorBridgeError as exc:
            await repo.log_event_by_type(
                run_id,
                AgentName.SENTINEL,
                "cursor_bridge_error",
                str(exc),
            )
            raise

        if progress:
            await progress.log("parse", "Parsing review JSON / text response")

        cli_stdout = str(result.get("cli_stdout") or result.get("raw_content") or "")
        cli_stderr = str(result.get("cli_stderr") or "")
        cli_meta = {
            "backend": result.get("backend"),
            "returncode": result.get("cli_returncode"),
            "timed_out": result.get("cli_timed_out"),
            "command": result.get("cli_command"),
        }
        if progress:
            if cli_stdout.strip():
                await progress.cli_output("stdout", cli_stdout, **cli_meta)
            if cli_stderr.strip():
                await progress.cli_output("stderr", cli_stderr, **cli_meta)

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
        return {
            "review": review,
            "executor": executor.value,
            "prompt": skill_prompt,
            "cli_stdout": cli_stdout,
            "cli_stderr": cli_stderr,
            "cli_command": result.get("cli_command"),
            "cli_returncode": result.get("cli_returncode"),
            "cli_timed_out": result.get("cli_timed_out"),
            "backend": result.get("backend"),
        }

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
