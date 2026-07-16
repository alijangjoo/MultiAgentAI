import json
import re
from typing import Any

from shared.agent_executors.cursor_client import CursorBridgeError, cursor_bridge_develop
from shared.agent_executors.models import AgentExecutorType
from shared.agent_executors.settings_store import get_agent_executor_settings
from shared.llm.factory import create_coding_llm_for_provider
from shared.models.domain import AgentName
from shared.persistence.repository import AgentRunRepository


def _parse_files_json(content: str, fallback_path: str, fallback_body: str) -> dict[str, str]:
    json_match = re.search(r"\{{[\s\S]*\}}", content)
    if json_match:
        return json.loads(json_match.group())
    return {fallback_path: fallback_body}


async def execute_develop(
    *,
    run_id: str,
    task_key: str,
    branch_name: str,
    subtask_title: str,
    subtask_description: str,
    prd_content: str,
    knowledge_context: str,
    repo: AgentRunRepository,
) -> dict[str, Any]:
    settings_store = get_agent_executor_settings()
    executor = settings_store.forge_executor

    await repo.log_event_by_type(
        run_id,
        AgentName.FORGE,
        "executor_selected",
        f"Develop executor: {executor}",
        {"executor": executor.value},
    )

    prompt = f"""You are Forge, a senior .NET 8 developer specializing in DDD/CQRS for the Dizi project.

Implement the following subtask on branch `{branch_name}`. After changes, commit and push to GitLab origin.

## Task: {task_key}
## Subtask: {subtask_title}
{subtask_description}

## PRD Context:
{prd_content[:3000]}

## Architecture Specs & Knowledge (MUST FOLLOW):
{knowledge_context[:12000]}

## Requirements:
- Follow **new-structure** layout under `src/` (AppCore, Endpoints, Infra) per architecture specs
- Use MediatR CQRS: commands/queries in AppCore/Shared, handlers in AppServices
- FluentValidation for commands
- Thin controllers in Endpoints using BaseApiController
- Do NOT use legacy Dizi/Features pattern unless task explicitly requires it

Return a JSON object mapping file paths to file contents if not pushing via git directly.
Example: {{"src/AppCore/Shared/Vendors/Commands/CreateVendorCommand.cs": "// code here"}}
"""

    if executor == AgentExecutorType.CURSOR:
        try:
            result = await cursor_bridge_develop(
                task_key=task_key,
                branch_name=branch_name,
                prompt=prompt,
                run_id=run_id,
            )
            files = result.get("files") or {}
            git_pushed = bool(result.get("git_pushed"))
            summary = result.get(
                "summary",
                f"Cursor implemented {len(files)} files on {branch_name}",
            )
            await repo.log_event_by_type(
                run_id,
                AgentName.FORGE,
                "cursor_develop_completed",
                summary,
                {"git_pushed": git_pushed, "files": list(files.keys())},
            )
            return {
                "generated_files": files,
                "development_summary": summary,
                "git_pushed_by_cursor": git_pushed,
                "executor": executor.value,
            }
        except CursorBridgeError as exc:
            await repo.log_event_by_type(
                run_id,
                AgentName.FORGE,
                "cursor_bridge_error",
                str(exc),
            )
            raise

    llm = create_coding_llm_for_provider(executor.value)
    await repo.log_event_by_type(
        run_id,
        AgentName.FORGE,
        "development_started",
        f"Developing subtask via {executor}: {subtask_title}",
    )

    response = await llm.ainvoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    files = _parse_files_json(
        content,
        f"src/Application/{subtask_title.replace(' ', '')}/Handler.cs",
        f"// Generated stub for: {subtask_title}\n// TODO: Implement based on PRD\n",
    )
    summary = f"[{executor}] Implemented {len(files)} files for subtask: {subtask_title}"
    return {
        "generated_files": files,
        "development_summary": summary,
        "git_pushed_by_cursor": False,
        "executor": executor.value,
    }
