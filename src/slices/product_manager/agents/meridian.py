"""Meridian - Product Manager Agent: gathers requirements via chat and produces PRD documents."""

from uuid import uuid4

from shared.llm.factory import create_pm_llm
from shared.models.domain import AgentName
from shared.persistence.repository import AgentRunRepository
from slices.product_manager.models.state import ChatMessage, MeridianSession
from slices.product_manager.template_loader import apply_prd_placeholders, load_prd_template


class MeridianSessionStore:
    _sessions: dict[str, MeridianSession] = {}

    @classmethod
    def get_or_create(cls, session_id: str | None) -> MeridianSession:
        if session_id and session_id in cls._sessions:
            return cls._sessions[session_id]
        new_id = session_id or str(uuid4())
        session = MeridianSession(id=new_id)
        cls._sessions[new_id] = session
        return session

    @classmethod
    def get(cls, session_id: str) -> MeridianSession | None:
        return cls._sessions.get(session_id)


async def chat_with_meridian(
    session_id: str | None,
    message: str,
    role: str,
    repo: AgentRunRepository | None = None,
) -> tuple[str, str, int]:
    session = MeridianSessionStore.get_or_create(session_id)
    session.messages.append(ChatMessage(role=role, content=message))

    conversation = "\n".join(f"{m.role}: {m.content}" for m in session.messages[-12:])
    llm = create_pm_llm()
    prompt = f"""You are Meridian, a Product Manager for a .NET microservices platform (Dizi/Vendor APIs).

Gather requirements from stakeholders and tech leads. Ask clarifying questions when needed.
Keep responses concise and structured. Focus on scope, user stories, acceptance criteria, and NFRs.

Conversation so far:
{conversation}

Respond as Meridian to the latest message from {role}."""

    if repo:
        await repo.log_event_by_type(
            session.id,
            AgentName.MERIDIAN,
            "chat_message",
            f"Chat from {role}: {message[:80]}",
        )

    response = await llm.ainvoke(prompt)
    reply = response.content if hasattr(response, "content") else str(response)
    session.messages.append(ChatMessage(role="meridian", content=reply))
    return session.id, reply, len(session.messages)


async def generate_prd(
    session_id: str,
    title: str | None,
    stakeholders: str,
    tech_lead: str,
    repo: AgentRunRepository,
) -> tuple[str, str, str]:
    session = MeridianSessionStore.get(session_id)
    if not session or not session.messages:
        raise ValueError("Session not found or empty. Start a chat first.")

    conversation = "\n".join(f"{m.role}: {m.content}" for m in session.messages)
    resolved_title = title or "New Feature Requirements"
    template = load_prd_template()
    scaffold = apply_prd_placeholders(
        template,
        title=resolved_title,
        stakeholders=stakeholders,
        tech_lead=tech_lead,
    )

    llm = create_pm_llm()
    prompt = f"""You are Meridian, a Product Manager. Fill in the PRD template based on the conversation.

Use the exact markdown structure from the template. Replace placeholder sections with concrete content.
Do not remove section headers. Write in English unless the conversation is in Persian.

## Conversation:
{conversation}

## PRD Template (fill all sections):
{scaffold}

Return the complete PRD markdown document only."""

    run_id = await repo.create_run(
        workflow_type="prd_workflow",
        agent_name=AgentName.MERIDIAN,
        input_payload={"session_id": session_id, "title": resolved_title},
    )
    await repo.update_run(run_id, status="running")
    await repo.log_event_by_type(
        run_id,
        AgentName.MERIDIAN,
        "prd_generation_started",
        f"Generating PRD: {resolved_title}",
    )

    response = await llm.ainvoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    prd_content = content.strip()

    if not prd_content.startswith("#"):
        prd_content = scaffold + "\n\n" + prd_content

    session.prd_content = prd_content
    session.prd_run_id = run_id

    await repo.update_run(
        run_id,
        status="completed",
        output_payload={"prd_content": prd_content[:5000], "title": resolved_title},
    )
    await repo.log_event_by_type(
        run_id,
        AgentName.MERIDIAN,
        "prd_generation_completed",
        f"PRD ready: {resolved_title}",
    )

    return run_id, prd_content, resolved_title


async def create_jira_from_prd(
    session_id: str,
    summary: str,
    prd_content: str | None,
    issue_type: str,
    labels: list[str],
    jira_client,
    repo: AgentRunRepository,
) -> str:
    session = MeridianSessionStore.get(session_id)
    if not session:
        raise ValueError("Session not found")

    description = prd_content or session.prd_content
    if not description:
        raise ValueError("No PRD content. Generate PRD first or provide prd_content.")

    run_id = await repo.create_run(
        workflow_type="prd_workflow",
        agent_name=AgentName.MERIDIAN,
        input_payload={"session_id": session_id, "summary": summary, "action": "create_jira"},
    )
    await repo.update_run(run_id, status="running")

    jira_key = await jira_client.create_story(
        summary=summary,
        description=description,
        issue_type=issue_type,
        labels=labels,
    )

    await repo.update_run(
        run_id,
        status="completed",
        output_payload={"jira_key": jira_key, "summary": summary},
    )
    await repo.log_event_by_type(
        run_id,
        AgentName.MERIDIAN,
        "jira_created",
        f"Created Jira {jira_key}: {summary}",
    )
    return jira_key


def build_incident_prd_prompt(report: dict, tech_lead: str) -> str:
    return f"""Incident reported in Mattermost requires a PRD and Jira task.

Severity: {report.get('severity')}
Title: {report.get('title')}
Summary: {report.get('summary')}
Root cause hypothesis: {report.get('root_cause_hypothesis')}
Affected services: {', '.join(report.get('affected_services', []))}
Recommended actions: {', '.join(report.get('recommended_actions', []))}
Elastic log evidence:
{chr(10).join(report.get('elastic_log_snippets', [])[:5])}

Tech Lead: {tech_lead}

As stakeholder, we need a PRD to prevent recurrence and track remediation work."""
