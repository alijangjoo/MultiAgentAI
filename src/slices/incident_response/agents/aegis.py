"""Aegis - Disaster Incident Analyst: monitors Mattermost, analyzes logs, reports to Tech Lead."""

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.config import get_settings
from shared.integrations.factory import IntegrationContainer
from shared.llm.factory import create_llm
from shared.models.domain import AgentName
from shared.persistence.repository import AgentRunRepository
from slices.incident_response.models.state import AegisOutput, IncidentReport


class AegisState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str
    channel_id: str
    posts: list[dict[str, Any]]
    logs: list[dict[str, Any]]
    traces: list[dict[str, Any]]
    knowledge_context: str
    report: IncidentReport | None
    error: str | None


async def fetch_mattermost_posts(
    state: AegisState,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> dict:
    posts = await integrations.mattermost.get_channel_posts(
        channel_id=state["channel_id"],
        limit=50,
    )

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.AEGIS,
        "posts_fetched",
        f"Fetched {len(posts)} posts from Disaster channel",
    )

    return {"posts": posts}


async def extract_incident_context(state: AegisState) -> dict:
    combined_text = " ".join(p.get("message", "") for p in state["posts"])
    keywords = []
    for word in combined_text.lower().split():
        if word in ("timeout", "error", "504", "503", "incident", "failed", "down", "payment"):
            keywords.append(word)
    return {"incident_keywords": list(set(keywords)), "combined_text": combined_text}


async def search_logs_and_traces(
    state: AegisState,
    integrations: IntegrationContainer,
    incident_keywords: list[str],
    combined_text: str,
) -> dict:
    settings = get_settings()
    query = " OR ".join(incident_keywords) if incident_keywords else combined_text[:200]
    logs = await integrations.elasticsearch.search_logs(
        query=query,
        time_range_minutes=120,
        size=30,
        service_name=settings.elasticsearch_service_name,
        service_environment=settings.elasticsearch_service_environment,
    )
    traces = await integrations.elasticsearch.search_traces(
        service_name=settings.elasticsearch_service_name,
        error=True,
        time_range_minutes=120,
    )
    return {"logs": logs, "traces": traces}


async def query_knowledge(
    state: AegisState,
    integrations: IntegrationContainer,
    combined_text: str,
) -> dict:
    context = await integrations.knowledge.query(
        question=combined_text[:500],
        context={"source": "incident_response", "channel": "disaster"},
    )
    knowledge_text = "\n".join(r.get("content", "") for r in context)
    return {"knowledge_context": knowledge_text}


async def generate_incident_report(
    state: AegisState,
    repo: AgentRunRepository,
) -> dict:
    settings = get_settings()
    vendor_names = [n.strip().lower() for n in settings.vendor_service_names.split(",") if n.strip()]

    posts_text = "\n".join(
        f"[{p.get('user_id', 'unknown')}]: {p.get('message', '')}" for p in state["posts"]
    )
    logs_text = "\n".join(str(log)[:300] for log in state["logs"][:10])
    traces_text = "\n".join(str(trace)[:300] for trace in state["traces"][:5])
    elastic_snippets = [
        f"{log.get('@timestamp', '')} [{log.get('level', '')}] {log.get('message', str(log))[:400]}"
        for log in state["logs"][:15]
    ]

    llm = create_llm(temperature=0.1)
    prompt = f"""You are Aegis, an incident response analyst for the Dizi Vendor microservices platform.

Analyze Disaster channel messages, Elasticsearch logs (service.name={settings.elasticsearch_service_name},
service.environment={settings.elasticsearch_service_environment}), and traces.
Determine if this incident is related to our team/vendor APIs (Dizi).

## Mattermost Disaster Channel Messages:
{posts_text[:4000]}

## Relevant Logs (Elasticsearch):
{logs_text[:3000]}

## APM Traces:
{traces_text[:2000]}

## Knowledge Base Context:
{state.get('knowledge_context', '')[:2000]}

Return JSON with these fields:
- severity: critical|high|medium|low
- title: short incident title
- summary: 2-3 sentence executive summary
- root_cause_hypothesis: best guess at root cause
- affected_services: list of service names
- is_vendor_related: true if incident affects Dizi/vendor APIs or our team's services
- timeline: list of {{time, event}} objects
- recommended_actions: list of immediate action items
- evidence: list of supporting evidence from logs/traces
- suggested_jira_summary: one-line Jira story title if vendor-related
- suggested_jira_description: markdown task body including relevant log snippets
"""

    await repo.log_event_by_type(
        state["run_id"],
        AgentName.AEGIS,
        "analysis_started",
        "Generating incident report for Tech Lead",
    )

    try:
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        import json
        import re

        json_match = re.search(r"\{{[\s\S]*\}}", content)
        if json_match:
            report_data = json.loads(json_match.group())
        else:
            report_data = {
                "severity": "high",
                "title": "Incident detected in Disaster channel",
                "summary": combined_text[:200] if (combined_text := posts_text[:200]) else "",
                "root_cause_hypothesis": "Unable to determine automatically",
                "affected_services": [],
                "timeline": [],
                "recommended_actions": ["Manual investigation required"],
                "evidence": [],
            }

        report = IncidentReport(
            severity=report_data.get("severity", "medium"),
            title=report_data.get("title", "Unknown Incident"),
            summary=report_data.get("summary", ""),
            root_cause_hypothesis=report_data.get("root_cause_hypothesis", ""),
            affected_services=report_data.get("affected_services", []),
            timeline=report_data.get("timeline", []),
            recommended_actions=report_data.get("recommended_actions", []),
            evidence=report_data.get("evidence", []),
            mattermost_posts_count=len(state["posts"]),
            logs_analyzed=len(state["logs"]),
            is_vendor_related=bool(report_data.get("is_vendor_related", False)),
            elastic_log_snippets=elastic_snippets or report_data.get("elastic_log_snippets", []),
            suggested_jira_summary=report_data.get("suggested_jira_summary", ""),
            suggested_jira_description=report_data.get(
                "suggested_jira_description",
                "\n".join(elastic_snippets[:5]),
            ),
        )

        if not report.is_vendor_related:
            combined_lower = posts_text.lower()
            report.is_vendor_related = any(v in combined_lower for v in vendor_names) or any(
                (svc or "").lower() in vendor_names for svc in report.affected_services
            )

        await repo.log_event_by_type(
            state["run_id"],
            AgentName.AEGIS,
            "analysis_completed",
            f"Report generated: {report.title} ({report.severity})",
        )

        return {"report": report}
    except Exception as exc:
        return {"error": str(exc), "report": None}


def build_aegis_graph(
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> StateGraph:
    graph = StateGraph(AegisState)

    async def fetch_posts_node(state: AegisState) -> dict:
        return await fetch_mattermost_posts(state, integrations, repo)

    async def investigate_node(state: AegisState) -> dict:
        ctx = await extract_incident_context(state)
        search_result = await search_logs_and_traces(
            state,
            integrations,
            ctx["incident_keywords"],
            ctx["combined_text"],
        )
        knowledge_result = await query_knowledge(state, integrations, ctx["combined_text"])
        return {**search_result, **knowledge_result}

    async def report_node(state: AegisState) -> dict:
        return await generate_incident_report(state, repo)

    graph.add_node("fetch_posts", fetch_posts_node)
    graph.add_node("investigate", investigate_node)
    graph.add_node("generate_report", report_node)

    graph.set_entry_point("fetch_posts")
    graph.add_edge("fetch_posts", "investigate")
    graph.add_edge("investigate", "generate_report")
    graph.add_edge("generate_report", END)

    return graph


async def run_aegis(
    run_id: str,
    channel_id: str | None,
    integrations: IntegrationContainer,
    repo: AgentRunRepository,
) -> AegisOutput:
    settings = get_settings()
    channel = channel_id or settings.mattermost_disaster_channel_id or "disaster"

    graph = build_aegis_graph(integrations, repo).compile()
    result = await graph.ainvoke(
        {
            "messages": [],
            "run_id": run_id,
            "channel_id": channel,
            "posts": [],
            "logs": [],
            "traces": [],
            "knowledge_context": "",
            "report": None,
            "error": None,
        }
    )

    if result.get("error") or not result.get("report"):
        raise RuntimeError(result.get("error", "Failed to generate incident report"))

    return AegisOutput(
        channel_id=channel,
        report=result["report"],
        posts_analyzed=len(result["posts"]),
        logs_found=len(result["logs"]),
    )
