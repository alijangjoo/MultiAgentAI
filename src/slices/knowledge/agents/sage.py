"""Sage - Knowledge Agent: RAG retrieval and synthesis."""

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.tracing import trace_config
from shared.llm.factory import create_llm
from shared.models.domain import AgentName
from shared.persistence.repository import AgentRunRepository
from slices.knowledge.models.collections import ALL_COLLECTIONS
from slices.knowledge.rag.vector_store import get_knowledge_store


class SageState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    question: str
    collections: list[str] | None
    top_k: int
    context: dict
    results: list[dict]
    answer: str | None
    error: str | None


async def retrieve_knowledge(state: SageState, repo: AgentRunRepository) -> dict:
    store = get_knowledge_store()
    results = store.query(
        question=state["question"],
        collections=state.get("collections"),
        top_k=state.get("top_k", 5),
    )
    await repo.log_event_by_type(
        state["run_id"],
        AgentName.SAGE,
        "retrieval_completed",
        f"Retrieved {len(results)} chunks",
        {"collections": state.get("collections") or ALL_COLLECTIONS},
    )
    return {"results": results}


async def synthesize_answer(state: SageState, repo: AgentRunRepository) -> dict:
    if not state.get("results"):
        return {
            "answer": "No relevant knowledge found in the vector store. Try ingesting documents first.",
        }

    context_blocks = []
    for i, r in enumerate(state["results"], 1):
        context_blocks.append(
            f"[{i}] ({r['collection']}) {r.get('title', 'Untitled')} (score={r['score']}):\n{r['content']}"
        )
    context_text = "\n\n".join(context_blocks)

    llm = create_llm(temperature=0.1)
    prompt = f"""You are Sage, the Knowledge Agent for a .NET 8 DDD/CQRS development team.

Answer the developer's question using ONLY the retrieved knowledge below.
Structure your answer with: Summary, Relevant Patterns/Solutions, Recommended Actions.
If information is insufficient, say what is missing.

## Question
{state['question']}

## Additional Context
{state.get('context', {})}

## Retrieved Knowledge
{context_text}
"""

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.SAGE,
        "synthesis_started",
        "Generating answer from retrieved knowledge",
    )

    try:
        response = await llm.ainvoke(prompt)
        answer = response.content if hasattr(response, "content") else str(response)
        await repo.log_event_by_type(
            state["run_id"],
            AgentName.SAGE,
            "synthesis_completed",
            "Answer generated",
        )
        return {"answer": answer}
    except Exception as exc:
        fallback = "\n\n".join(r["content"] for r in state["results"][:3])
        return {"answer": fallback, "error": str(exc)}


def build_sage_graph(repo: AgentRunRepository) -> StateGraph:
    graph = StateGraph(SageState)

    async def retrieve_node(state: SageState) -> dict:
        return await retrieve_knowledge(state, repo)

    async def synthesize_node(state: SageState) -> dict:
        return await synthesize_answer(state, repo)

    graph.add_node("retrieve", retrieve_node)
    graph.add_node("synthesize", synthesize_node)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("synthesize", END)
    return graph


async def run_sage(
    run_id: str,
    question: str,
    collections: list[str] | None,
    top_k: int,
    context: dict,
    repo: AgentRunRepository,
) -> dict:
    graph = build_sage_graph(repo).compile()
    return await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "question": question,
            "collections": collections,
            "top_k": top_k,
            "context": context or {},
            "results": [],
            "answer": None,
            "error": None,
        },
        config=trace_config(
            run_id=run_id,
            agent_name="sage",
            workflow_type="knowledge_query",
        ),
    )
