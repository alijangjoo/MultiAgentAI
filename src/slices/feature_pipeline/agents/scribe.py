"""Scribe - Documentation Agent: updates Confluence after merge."""

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.config import get_settings
from core.tracing import trace_config
from shared.integrations.factory import IntegrationContainer
from shared.llm.factory import create_llm
from shared.models.domain import AgentName
from shared.persistence.repository import AgentRunRepository
from slices.feature_pipeline.models.state import ScribeOutput


class ScribeState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    task_key: str
    task_summary: str
    development_summary: str
    review_summary: str
    confluence_page_id: str | None
    page_id: str
    page_title: str
    doc_content: str
    updated: bool
    error: str | None


async def find_or_create_page(state: ScribeState, integrations: IntegrationContainer) -> dict:
    settings = get_settings()
    page_id = state.get("confluence_page_id")

    if page_id:
        return {"page_id": page_id, "page_title": f"{state['task_summary']} Documentation"}

    pages = await integrations.confluence.search_pages(
        query=state["task_summary"],
        space_key=settings.confluence_space_key,
    )
    if pages:
        return {"page_id": pages[0]["id"], "page_title": pages[0].get("title", "")}

    page = await integrations.confluence.create_page(
        space_key=settings.confluence_space_key,
        title=f"{state['task_key']}: {state['task_summary']}",
        content="<p>Documentation placeholder</p>",
    )
    return {"page_id": page["id"], "page_title": page.get("title", "")}


async def generate_documentation(state: ScribeState, repo: AgentRunRepository) -> dict:
    llm = create_llm()
    prompt = f"""You are Scribe, a technical documentation writer.

Generate Confluence storage-format HTML documentation for a completed feature.

## Task: {state['task_key']} - {state['task_summary']}
## Development Summary: {state['development_summary']}
## Code Review Summary: {state['review_summary']}

Include sections:
- Overview
- API Endpoints (if applicable)
- Domain Model Changes
- Configuration Changes
- Deployment Notes

Return only the HTML content suitable for Confluence storage format.
"""

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.SCRIBE,
        "documentation_started",
        f"Generating docs for {state['task_key']}",
    )

    try:
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return {"doc_content": content}
    except Exception as exc:
        return {"error": str(exc), "doc_content": f"<p>Documentation generation failed: {exc}</p>"}


async def update_confluence(
    state: ScribeState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
    doc_content: str,
) -> dict:
    title = f"{state['task_key']}: {state['task_summary']}"
    await integrations.confluence.update_page(
        page_id=state["page_id"],
        title=title,
        content=doc_content,
    )

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.SCRIBE,
        "documentation_updated",
        f"Confluence page {state['page_id']} updated",
    )

    return {"updated": True, "page_title": title}


def build_scribe_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(ScribeState)

    async def find_page_node(state: ScribeState) -> dict:
        return await find_or_create_page(state, integrations)

    async def generate_node(state: ScribeState) -> dict:
        return await generate_documentation(state, repo)

    async def update_node(state: ScribeState) -> dict:
        doc_content = state.get("doc_content", "")
        if state.get("error"):
            return {"updated": False}
        return await update_confluence(state, integrations, repo, doc_content)

    graph.add_node("find_page", find_page_node)
    graph.add_node("generate", generate_node)
    graph.add_node("update", update_node)

    graph.set_entry_point("find_page")
    graph.add_edge("find_page", "generate")
    graph.add_edge("generate", "update")
    graph.add_edge("update", END)

    return graph


async def run_scribe(
    run_id: str,
    task_key: str,
    task_summary: str,
    development_summary: str,
    review_summary: str,
    confluence_page_id: str | None,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> ScribeOutput:
    graph = build_scribe_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "task_key": task_key,
            "task_summary": task_summary,
            "development_summary": development_summary,
            "review_summary": review_summary,
            "confluence_page_id": confluence_page_id,
            "page_id": "",
            "page_title": "",
            "doc_content": "",
            "updated": False,
            "error": None,
        },
        config=trace_config(
            run_id=run_id,
            agent_name="scribe",
            workflow_type="feature_development",
        ),
    )

    if result.get("error"):
        raise RuntimeError(result["error"])

    return ScribeOutput(
        page_id=result["page_id"],
        page_title=result.get("page_title", ""),
        updated=result.get("updated", False),
    )
