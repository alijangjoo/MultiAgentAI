"""Execute branch QA via Cursor Bridge or LLM API."""

from __future__ import annotations

import json
from typing import Any

from core.config import get_settings
from core.tracing import trace_config
from shared.agent_executors.cursor_client import CursorBridgeError, cursor_bridge_qa
from shared.agent_executors.models import AgentExecutorType
from shared.agent_executors.settings_store import get_agent_executor_settings
from shared.llm.factory import create_code_review_llm_for_provider
from shared.models.domain import AgentName
from shared.persistence.repository import AgentRunRepository
from shared.qa.models import QaContext, QaResult
from shared.qa.prompt_builder import build_qa_prompt
from shared.qa.response_parser import parse_qa_response


async def execute_qa(
    *,
    run_id: str,
    context: QaContext,
    repo: AgentRunRepository,
    repo_path: str | None = None,
) -> dict[str, Any]:
    settings_store = get_agent_executor_settings()
    executor = settings_store.sentinel_executor

    await repo.log_event_by_type(
        run_id,
        AgentName.QA,
        "executor_selected",
        f"QA executor: {executor.value}",
        {"executor": executor.value},
    )

    prompt = build_qa_prompt(context)
    settings = get_settings()

    if executor == AgentExecutorType.CURSOR:
        try:
            bridge_result = await cursor_bridge_qa(
                run_id=run_id,
                task_key=context.task_key or "",
                branch_name=context.branch_name,
                context=context.model_dump(),
                model=settings.code_review_model,
                repo_path=repo_path,
            )
            qa_data = bridge_result.get("qa") or {}
            result = _coerce_qa_result(qa_data, fallback_summary=str(qa_data.get("summary") or ""))
            return {
                "result": result.model_dump(),
                "executor": executor.value,
                "backend": bridge_result.get("backend", "cursor"),
                "prompt": prompt,
                "cli_stdout": bridge_result.get("cli_stdout", ""),
                "cli_stderr": bridge_result.get("cli_stderr", ""),
                "raw_content": bridge_result.get("raw_content", ""),
            }
        except CursorBridgeError as exc:
            await repo.log_event_by_type(
                run_id,
                AgentName.QA,
                "cursor_bridge_failed",
                str(exc),
            )
            if settings.llm_api_key:
                executor = AgentExecutorType.OPENAI
            else:
                raise

    llm = create_code_review_llm_for_provider(executor.value)
    response = await llm.ainvoke(prompt, config=trace_config(run_id, AgentName.QA, "branch_qa"))
    content = response.content if hasattr(response, "content") else str(response)
    result = parse_qa_response(str(content))
    return {
        "result": result.model_dump(),
        "executor": executor.value,
        "backend": "llm",
        "prompt": prompt,
        "cli_stdout": str(content)[:16000],
        "cli_stderr": "",
        "raw_content": str(content)[:16000],
    }


def _coerce_qa_result(data: dict[str, Any] | None, *, fallback_summary: str = "") -> QaResult:
    if not data:
        return QaResult(summary=fallback_summary, verdict="FAIL")
    try:
        return QaResult(**data)
    except Exception:
        return parse_qa_response(json.dumps(data))
