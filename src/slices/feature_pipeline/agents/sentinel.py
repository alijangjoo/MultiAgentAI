"""Sentinel - Code Review Agent: creates MR and performs automated code review."""

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.config import get_settings
from shared.integrations.factory import IntegrationContainer
from shared.agent_executors.review_executor import execute_review
from shared.models.domain import AgentName, CodeReviewResult, MergeRequestInfo
from shared.persistence.repository import AgentRunRepository
from slices.feature_pipeline.models.state import SentinelOutput


class SentinelState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    task_key: str
    branch_name: str
    task_summary: str
    development_summary: str
    merge_request: MergeRequestInfo | None
    mr_changes: list[dict] | None
    review: CodeReviewResult | None
    error: str | None


async def create_merge_request(
    state: SentinelState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    settings = get_settings()
    title = f"[{state['task_key']}] {state['task_summary']}"
    description = (
        f"## Summary\n{state['development_summary']}\n\n"
        f"## Jira\n{state['task_key']}\n\n"
        f"## Review\nAutomated review by Sentinel agent pending.\n\n"
        f"**Human merge required** - Tech Lead approval needed."
    )

    mr_data = await integrations.gitlab.create_merge_request(
        source_branch=state["branch_name"],
        target_branch=settings.gitlab_default_branch,
        title=title,
        description=description,
    )

    mr = MergeRequestInfo(
        iid=mr_data["iid"],
        url=mr_data["web_url"],
        title=mr_data["title"],
        source_branch=mr_data["source_branch"],
        target_branch=mr_data["target_branch"],
    )

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.SENTINEL,
        "mr_created",
        f"Merge request !{mr.iid} created",
        {"url": mr.url},
    )

    return {"merge_request": mr}


async def perform_code_review(
    state: SentinelState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    mr = state["merge_request"]
    if not mr:
        return {"error": "No merge request to review"}

    mr_changes = state.get("mr_changes") or []
    if mr_changes:
        code_context = "\n\n".join(
            f"### {change.get('new_path') or change.get('old_path')}\n{change.get('diff', '')[:2500]}"
            for change in mr_changes[:20]
        )
    else:
        code_samples = []
        for file_path in ["src/Application", "src/Domain", "src/Infrastructure"]:
            try:
                content = await integrations.gitlab.get_file_content(file_path, state["branch_name"])
                code_samples.append(f"### {file_path}\n{content[:1500]}")
            except Exception:
                continue
        code_context = "\n\n".join(code_samples) if code_samples else state["development_summary"]

    try:
        result = await execute_review(
            run_id=state["run_id"],
            task_key=state["task_key"],
            branch_name=state["branch_name"],
            mr=mr,
            development_summary=state["development_summary"],
            code_context=code_context,
            mr_changes=mr_changes,
            repo=repo,
        )
        return {"review": result["review"]}
    except Exception as exc:
        return {
            "error": str(exc),
            "review": CodeReviewResult(
                approved=False,
                summary=f"Review failed: {exc}",
                findings=["Automated review error"],
                suggestions=["Manual review required"],
            ),
        }


def build_sentinel_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(SentinelState)

    async def mr_node(state: SentinelState) -> dict:
        return await create_merge_request(state, integrations, repo)

    async def review_node(state: SentinelState) -> dict:
        return await perform_code_review(state, integrations, repo)

    graph.add_node("create_mr", mr_node)
    graph.add_node("code_review", review_node)

    graph.set_entry_point("create_mr")
    graph.add_edge("create_mr", "code_review")
    graph.add_edge("code_review", END)

    return graph


def build_sentinel_review_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(SentinelState)

    async def review_node(state: SentinelState) -> dict:
        return await perform_code_review(state, integrations, repo)

    graph.add_node("code_review", review_node)
    graph.set_entry_point("code_review")
    graph.add_edge("code_review", END)
    return graph


async def run_sentinel(
    run_id: str,
    task_key: str,
    branch_name: str,
    task_summary: str,
    development_summary: str,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> SentinelOutput:
    graph = build_sentinel_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "task_key": task_key,
            "branch_name": branch_name,
            "task_summary": task_summary,
            "development_summary": development_summary,
            "merge_request": None,
            "mr_changes": None,
            "review": None,
            "error": None,
        }
    )

    return SentinelOutput(
        merge_request=result["merge_request"],
        review=result["review"],
    )


async def run_sentinel_review(
    run_id: str,
    merge_request: MergeRequestInfo,
    mr_changes: list[dict],
    task_key: str,
    development_summary: str,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> SentinelOutput:
    """Review an existing merge request without creating a new one."""
    graph = build_sentinel_review_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "task_key": task_key,
            "branch_name": merge_request.source_branch,
            "task_summary": merge_request.title,
            "development_summary": development_summary,
            "merge_request": merge_request,
            "mr_changes": mr_changes,
            "review": None,
            "error": None,
        }
    )

    return SentinelOutput(
        merge_request=merge_request,
        review=result["review"],
    )
