"""LangGraph workflow: full dashboard-driven development (branch → specs → forge → MR)."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.tracing import trace_config
from shared.deploy_settings.store import resolve_source_branch, resolve_target_branch
from shared.integrations.factory import IntegrationContainer
from shared.llm.factory import create_llm
from shared.models.domain import AgentName, MergeRequestInfo, SubTask
from shared.persistence.repository import AgentRunRepository
from shared.utils.branch_naming import build_feature_branch_name, slugify
from slices.feature_pipeline.agents.forge import build_forge_graph
from slices.feature_pipeline.models.state import ForgeOutput
from slices.knowledge.models.collections import KnowledgeCollection
from slices.knowledge.specs.service import ArchitectureSpecService


class DevelopWorkflowState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    task_key: str
    environment: str
    source_branch: str
    target_branch: str
    short_description: str
    create_mr: bool
    issue: dict
    attachment_contents: list[dict]
    task_analysis: str
    prd_content: str
    branch_name: str
    architecture_specs_context: str
    subtask: SubTask
    forge_result: dict
    merge_request: MergeRequestInfo | None
    error: str | None


async def fetch_and_analyze_task(
    state: DevelopWorkflowState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    task_key = state["task_key"]
    issue = await integrations.jira.get_issue(task_key)
    prd = await integrations.jira.get_prd_attachment_content(task_key) or ""
    attachments: list[dict] = await integrations.jira.get_attachment_contents(task_key)

    attachment_text = "\n\n".join(
        f"### {a.get('filename', 'attachment')}\n{a.get('content', '')[:4000]}"
        for a in attachments
        if a.get("content")
    )

    llm = create_llm(temperature=0.1)
    prompt = f"""You are Atlas preparing a development brief for Forge (.NET 8 DDD/CQRS).

Summarize requirements, acceptance criteria, and technical constraints from the Jira task and attachments.
Prefer new-structure (src/) patterns unless the task explicitly targets legacy Dizi/Features.

## Task {task_key}
Summary: {issue.get('summary', '')}
Description:
{issue.get('description', '')[:6000]}

## PRD
{prd[:4000]}

## Attachments
{attachment_text[:8000] or 'No attachment content'}

Write a concise development brief (max 1500 words) for the implementing developer.
"""

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.ATLAS,
        "task_analysis_started",
        f"Analyzing {task_key} and attachments",
    )

    try:
        response = await llm.ainvoke(prompt)
        analysis = response.content if hasattr(response, "content") else str(response)
    except Exception as exc:
        analysis = (
            f"{issue.get('summary', '')}\n\n{issue.get('description', '')}\n\n{prd}"
        )[:8000]
        await repo.log_event_by_type(
            state["run_id"],
            AgentName.ATLAS,
            "task_analysis_fallback",
            str(exc),
        )

    return {
        "issue": issue,
        "attachment_contents": attachments,
        "task_analysis": analysis,
        "prd_content": prd or analysis[:4000],
    }


async def create_feature_branch(
    state: DevelopWorkflowState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    if state.get("error"):
        return {}

    issue = state["issue"]
    short_desc = state.get("short_description") or slugify(issue.get("summary", ""))
    branch_name = state.get("branch_name") or build_feature_branch_name(
        task_key=state["task_key"],
        task_summary=issue.get("summary", ""),
        short_description=short_desc,
    )
    source = state.get("source_branch") or resolve_source_branch()

    result = await integrations.gitlab.create_branch(branch_name=branch_name, ref=source)

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.FORGE,
        "branch_created",
        f"Branch {branch_name} from {source}",
        {"created": result.get("created", True), "exists": result.get("exists", False)},
    )

    subtask = SubTask(
        title=issue.get("summary", state["task_key"]),
        description=state.get("task_analysis") or issue.get("description", ""),
        estimated_hours=8.0,
    )

    return {"branch_name": branch_name, "subtask": subtask}


async def gather_architecture_specs(
    state: DevelopWorkflowState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    issue = state["issue"]
    topic = f"{issue.get('summary', '')} {state.get('task_analysis', '')[:500]}"

    spec_service = ArchitectureSpecService()
    spec_items = spec_service.list_specs(structure_tag="new-structure")
    baseline_ids = [
        "dizi.new-structure.overview",
        "dizi.new-structure.patterns.cqrs",
    ]
    baseline_blocks: list[str] = []
    for spec_id in baseline_ids:
        try:
            spec = spec_service.get_spec(spec_id)
            baseline_blocks.append(spec["markdown"][:3000])
        except FileNotFoundError:
            continue

    rag_results = await integrations.knowledge.query(
        question=topic,
        context={"collections": [KnowledgeCollection.ARCHITECTURE_SPEC.value], "structure_tag": "new-structure"},
        top_k=8,
    )

    rag_text = "\n\n---\n\n".join(
        f"[{r.get('title', r.get('source', 'spec'))}]\n{r.get('content', '')}"
        for r in rag_results
    )

    catalog = "\n".join(f"- {s['spec_id']}: {s['title']}" for s in spec_items[:20])
    combined = (
        "## Architecture Spec Catalog (new-structure)\n"
        f"{catalog}\n\n"
        "## Baseline Specs\n"
        f"{chr(10).join(baseline_blocks)}\n\n"
        "## Relevant Specs (RAG)\n"
        f"{rag_text}"
    )[:24000]

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.SAGE,
        "specs_loaded",
        f"Loaded {len(spec_items)} specs, {len(rag_results)} RAG hits",
    )

    return {"architecture_specs_context": combined}


async def run_forge_development(
    state: DevelopWorkflowState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    if state.get("error"):
        return {}

    knowledge_context = (
        f"## Architecture Specs (MUST FOLLOW)\n{state.get('architecture_specs_context', '')}\n\n"
        f"## Task Analysis\n{state.get('task_analysis', '')}"
    )

    graph = build_forge_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": state["run_id"],
            "task_key": state["task_key"],
            "branch_name": state["branch_name"],
            "subtask": state["subtask"],
            "prd_content": state.get("prd_content", ""),
            "knowledge_context": knowledge_context,
            "generated_files": {},
            "development_summary": "",
            "git_pushed_by_cursor": False,
            "error": None,
        },
        config=trace_config(
            run_id=state["run_id"],
            agent_name="forge",
            workflow_type="develop_workflow",
        ),
    )

    if result.get("error"):
        return {"error": result["error"], "forge_result": result}

    return {"forge_result": result}


async def create_develop_merge_request(
    state: DevelopWorkflowState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    if state.get("error") or not state.get("create_mr", True):
        return {}

    forge = state.get("forge_result") or {}
    issue = state["issue"]
    target = state.get("target_branch") or resolve_target_branch(state.get("environment", "dev"))
    summary = forge.get("development_summary", "")

    title = f"[{state['task_key']}] {issue.get('summary', state['task_key'])}"
    description = (
        f"## Summary\n{summary}\n\n"
        f"## Jira\n{state['task_key']}\n\n"
        f"## Environment\n{state.get('environment', 'dev')} → `{target}`\n\n"
        f"## Architecture\nDeveloped following **new-structure** specs from Knowledge Agent.\n\n"
        f"**Automated MR** — review required before merge."
    )

    mr_data = await integrations.gitlab.create_merge_request(
        source_branch=state["branch_name"],
        target_branch=target,
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
        f"MR !{mr.iid} → {target}",
        {"url": mr.url, "target_branch": target},
    )

    return {"merge_request": mr}


def build_develop_workflow_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(DevelopWorkflowState)

    async def analyze_node(s: DevelopWorkflowState) -> dict:
        return await fetch_and_analyze_task(s, integrations, repo)

    async def branch_node(s: DevelopWorkflowState) -> dict:
        return await create_feature_branch(s, integrations, repo)

    async def specs_node(s: DevelopWorkflowState) -> dict:
        return await gather_architecture_specs(s, integrations, repo)

    async def forge_node(s: DevelopWorkflowState) -> dict:
        return await run_forge_development(s, integrations, repo)

    async def mr_node(s: DevelopWorkflowState) -> dict:
        return await create_develop_merge_request(s, integrations, repo)

    graph.add_node("analyze_task", analyze_node)
    graph.add_node("create_branch", branch_node)
    graph.add_node("gather_specs", specs_node)
    graph.add_node("forge_develop", forge_node)
    graph.add_node("create_mr", mr_node)

    graph.set_entry_point("analyze_task")
    graph.add_edge("analyze_task", "create_branch")
    graph.add_edge("create_branch", "gather_specs")
    graph.add_edge("gather_specs", "forge_develop")
    graph.add_edge("forge_develop", "create_mr")
    graph.add_edge("create_mr", END)

    return graph


async def run_develop_workflow(
    *,
    run_id: str,
    task_key: str,
    environment: str,
    source_branch: str,
    target_branch: str,
    short_description: str,
    branch_name: str | None,
    create_mr: bool,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    graph = build_develop_workflow_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "task_key": task_key.upper(),
            "environment": environment,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "short_description": short_description,
            "create_mr": create_mr,
            "issue": {},
            "attachment_contents": [],
            "task_analysis": "",
            "prd_content": "",
            "branch_name": branch_name or "",
            "architecture_specs_context": "",
            "subtask": SubTask(title="", description="", estimated_hours=8),
            "forge_result": {},
            "merge_request": None,
            "error": None,
        },
        config=trace_config(
            run_id=run_id,
            agent_name="develop_workflow",
            workflow_type="develop_workflow",
        ),
    )

    if result.get("error"):
        raise RuntimeError(result["error"])

    forge = result.get("forge_result") or {}
    mr = result.get("merge_request")

    return {
        "branch_name": result["branch_name"],
        "files_changed": list(forge.get("generated_files", {}).keys()),
        "development_summary": forge.get("development_summary", ""),
        "merge_request": mr,
        "task_analysis": result.get("task_analysis", ""),
    }
