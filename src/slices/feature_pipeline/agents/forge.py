"""Forge - Developer Agent: implements subtasks using knowledge service."""

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.tracing import trace_config
from shared.integrations.factory import IntegrationContainer
from shared.agent_executors.develop_executor import execute_develop
from shared.models.domain import AgentName, SubTask
from shared.persistence.repository import AgentRunRepository
from slices.feature_pipeline.models.state import ForgeOutput


class ForgeState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    task_key: str
    branch_name: str
    subtask: SubTask
    prd_content: str
    knowledge_context: str
    generated_files: dict[str, str]
    development_summary: str
    git_pushed_by_cursor: bool
    error: str | None


async def gather_knowledge(state: ForgeState, integrations: IntegrationContainer) -> dict:
    if state.get("knowledge_context"):
        return {}
    subtask = state["subtask"]
    context = await integrations.knowledge.query(
        question=f"{subtask.title} {subtask.description}",
        context={"task_key": state["task_key"], "architecture": "dotnet8-cqrs-ddd"},
    )
    knowledge_text = "\n".join(r.get("content", "") for r in context)
    return {"knowledge_context": knowledge_text}


async def generate_code(state: ForgeState, repo: AgentRunRepository) -> dict:
    subtask = state["subtask"]
    try:
        result = await execute_develop(
            run_id=state["run_id"],
            task_key=state["task_key"],
            branch_name=state["branch_name"],
            subtask_title=subtask.title,
            subtask_description=subtask.description,
            prd_content=state.get("prd_content", ""),
            knowledge_context=state.get("knowledge_context", ""),
            repo=repo,
        )
        return {
            "generated_files": result.get("generated_files", {}),
            "development_summary": result.get("development_summary", ""),
            "git_pushed_by_cursor": result.get("git_pushed_by_cursor", False),
        }
    except Exception as exc:
        return {"error": str(exc), "generated_files": {}, "development_summary": ""}


async def commit_to_gitlab(
    state: ForgeState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    if state.get("error"):
        return {}

    if state.get("git_pushed_by_cursor"):
        await repo.log_event_by_type(
            state["run_id"],
            AgentName.FORGE,
            "development_completed",
            "Changes committed and pushed via Cursor (GitLab)",
            {"git_pushed": True},
        )
        return {}

    if not state.get("generated_files"):
        return {}

    subtask = state["subtask"]
    commit_message = f"feat({state['task_key']}): {subtask.title}"

    await integrations.gitlab.commit_files(
        branch=state["branch_name"],
        commit_message=commit_message,
        files=state["generated_files"],
    )

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.FORGE,
        "development_completed",
        f"Committed {len(state['generated_files'])} files",
        {"files": list(state["generated_files"].keys())},
    )

    return {}


def build_forge_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(ForgeState)

    async def knowledge_node(state: ForgeState) -> dict:
        return await gather_knowledge(state, integrations)

    async def code_node(state: ForgeState) -> dict:
        return await generate_code(state, repo)

    async def commit_node(state: ForgeState) -> dict:
        return await commit_to_gitlab(state, integrations, repo)

    graph.add_node("gather_knowledge", knowledge_node)
    graph.add_node("generate_code", code_node)
    graph.add_node("commit", commit_node)

    graph.set_entry_point("gather_knowledge")
    graph.add_edge("gather_knowledge", "generate_code")
    graph.add_edge("generate_code", "commit")
    graph.add_edge("commit", END)

    return graph


async def run_forge(
    run_id: str,
    task_key: str,
    branch_name: str,
    subtask: SubTask,
    prd_content: str,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> ForgeOutput:
    graph = build_forge_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "task_key": task_key,
            "branch_name": branch_name,
            "subtask": subtask,
            "prd_content": prd_content,
            "knowledge_context": "",
            "generated_files": {},
            "development_summary": "",
            "git_pushed_by_cursor": False,
            "error": None,
        },
        config=trace_config(
            run_id=run_id,
            agent_name="forge",
            workflow_type="feature_development",
        ),
    )

    if result.get("error"):
        raise RuntimeError(result["error"])

    return ForgeOutput(
        task_key=task_key,
        branch_name=branch_name,
        subtask_key=subtask.jira_key,
        files_changed=list(result.get("generated_files", {}).keys()),
        commit_message=f"feat({task_key}): {subtask.title}",
        development_summary=result.get("development_summary", ""),
    )
