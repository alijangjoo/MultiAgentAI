"""Atlas - Task Analyst Agent: analyzes Jira tasks, reads PRD, creates subtasks, creates branch."""

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.config import get_settings
from core.tracing import trace_config
from shared.integrations.factory import IntegrationContainer
from shared.llm.factory import create_llm
from shared.models.domain import AgentName, BranchInfo, SubTask
from shared.persistence.repository import AgentRunRepository
from shared.utils.branch_naming import build_feature_branch_name
from slices.feature_pipeline.models.state import AtlasOutput


class AtlasState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    task_key: str
    issue: dict
    prd_content: str
    subtasks: list[SubTask]
    branch: BranchInfo | None
    error: str | None


async def fetch_task(state: AtlasState, integrations: IntegrationContainer) -> dict:
    issue = await integrations.jira.get_issue(state["task_key"])
    prd = await integrations.jira.get_prd_attachment_content(state["task_key"])
    return {"issue": issue, "prd_content": prd or ""}


async def analyze_and_decompose(
    state: AtlasState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    issue = state["issue"]
    prd = state["prd_content"]

    knowledge = await integrations.knowledge.get_architecture_context(
        f"{issue.get('summary', '')} {issue.get('description', '')}"
    )

    llm = create_llm()
    prompt = f"""You are Atlas, a senior task analyst for a .NET 8 DDD/CQRS team.

Analyze this Jira task and PRD, then decompose into subtasks.
Each subtask MUST be completable within 1 day (max 8 hours).

## Jira Task: {state['task_key']}
Summary: {issue.get('summary', '')}
Description: {issue.get('description', '')}

## PRD Content:
{prd[:4000]}

## Architecture Context:
{knowledge[:2000]}

Return a JSON array of subtasks with fields: title, description, estimated_hours (max 8).
Focus on vertical slices: domain model, command handler, query handler, API endpoint, tests.
"""

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.ATLAS,
        "analysis_started",
        f"Analyzing task {state['task_key']}",
    )

    try:
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        import json
        import re

        json_match = re.search(r"\[[\s\S]*\]", content)
        if json_match:
            raw_subtasks = json.loads(json_match.group())
        else:
            raw_subtasks = [
                {
                    "title": f"Implement {issue.get('summary', state['task_key'])}",
                    "description": issue.get("description", ""),
                    "estimated_hours": 8,
                }
            ]

        subtasks = []
        for raw in raw_subtasks:
            hours = min(float(raw.get("estimated_hours", 8)), 8.0)
            subtasks.append(
                SubTask(
                    title=raw["title"],
                    description=raw.get("description", ""),
                    estimated_hours=hours,
                )
            )

        return {"subtasks": subtasks}
    except Exception as exc:
        return {"error": str(exc), "subtasks": []}


async def create_jira_subtasks(
    state: AtlasState,
    integrations: IntegrationContainer,
) -> dict:
    if state.get("error"):
        return {}

    updated_subtasks = []
    for subtask in state["subtasks"]:
        jira_key = await integrations.jira.create_subtask(
            parent_key=state["task_key"],
            summary=subtask.title,
            description=subtask.description,
            estimated_hours=subtask.estimated_hours,
        )
        updated_subtasks.append(subtask.model_copy(update={"jira_key": jira_key}))

    return {"subtasks": updated_subtasks}


async def create_git_branch(
    state: AtlasState,
    integrations: IntegrationContainer,
) -> dict:
    if state.get("error"):
        return {}

    issue = state["issue"]
    short_desc = issue.get("summary", "feature")[:50]
    branch_name = build_feature_branch_name(
        task_key=state["task_key"],
        task_summary=issue.get("summary", ""),
        short_description=short_desc,
    )

    settings = get_settings()
    await integrations.gitlab.create_branch(
        branch_name=branch_name,
        ref=settings.gitlab_feature_source_branch,
    )

    branch = BranchInfo(
        name=branch_name,
        task_key=state["task_key"],
        short_description=short_desc,
    )
    return {"branch": branch}


def build_atlas_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(AtlasState)

    async def fetch_node(state: AtlasState) -> dict:
        return await fetch_task(state, integrations)

    async def analyze_node(state: AtlasState) -> dict:
        return await analyze_and_decompose(state, integrations, repo)

    async def subtasks_node(state: AtlasState) -> dict:
        return await create_jira_subtasks(state, integrations)

    async def branch_node(state: AtlasState) -> dict:
        return await create_git_branch(state, integrations)

    graph.add_node("fetch_task", fetch_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("create_subtasks", subtasks_node)
    graph.add_node("create_branch", branch_node)

    graph.set_entry_point("fetch_task")
    graph.add_edge("fetch_task", "analyze")
    graph.add_edge("analyze", "create_subtasks")
    graph.add_edge("create_subtasks", "create_branch")
    graph.add_edge("create_branch", END)

    return graph


async def run_atlas(
    run_id: str,
    task_key: str,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> AtlasOutput:
    graph = build_atlas_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "task_key": task_key,
            "issue": {},
            "prd_content": "",
            "subtasks": [],
            "branch": None,
            "error": None,
        },
        config=trace_config(
            run_id=run_id,
            agent_name="atlas",
            workflow_type="feature_development",
        ),
    )

    if result.get("error"):
        raise RuntimeError(result["error"])

    return AtlasOutput(
        task_key=task_key,
        issue=result["issue"],
        subtasks=result["subtasks"],
        branch=result["branch"],
        prd_content=result["prd_content"],
    )
