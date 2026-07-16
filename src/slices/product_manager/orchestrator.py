from core.config import get_settings
from shared.integrations.registry import get_integrations
from shared.persistence.repository import AgentRunRepository
from slices.product_manager.agents.meridian import (
    MeridianSessionStore,
    build_incident_prd_prompt,
    chat_with_meridian,
    create_jira_from_prd,
    generate_prd,
)
from slices.product_manager.models.state import (
    MeridianChatOutput,
    MeridianJiraOutput,
    MeridianPRDOutput,
)


class ProductManagerOrchestrator:
    def __init__(self, run_repo: AgentRunRepository | None = None):
        self._integrations = get_integrations()
        self._run_repo = run_repo or AgentRunRepository()
        self._settings = get_settings()

    async def chat(
        self,
        session_id: str | None,
        message: str,
        role: str = "stakeholder",
    ) -> MeridianChatOutput:
        sid, reply, count = await chat_with_meridian(
            session_id=session_id,
            message=message,
            role=role,
        )
        return MeridianChatOutput(session_id=sid, reply=reply, message_count=count)

    async def generate_prd(
        self,
        session_id: str,
        title: str | None = None,
        stakeholders: str = "",
        tech_lead: str = "",
    ) -> MeridianPRDOutput:
        run_id, content, resolved_title = await generate_prd(
            session_id=session_id,
            title=title,
            stakeholders=stakeholders,
            tech_lead=tech_lead,
            repo=self._run_repo,
        )
        return MeridianPRDOutput(
            session_id=session_id,
            run_id=run_id,
            prd_content=content,
            title=resolved_title,
        )

    async def create_jira_task(
        self,
        session_id: str,
        summary: str,
        prd_content: str | None = None,
        issue_type: str = "Story",
        labels: list[str] | None = None,
    ) -> MeridianJiraOutput:
        jira_key = await create_jira_from_prd(
            session_id=session_id,
            summary=summary,
            prd_content=prd_content,
            issue_type=issue_type,
            labels=labels or ["meridian-prd"],
            jira_client=self._integrations.jira,
            repo=self._run_repo,
        )
        return MeridianJiraOutput(session_id=session_id, jira_key=jira_key, summary=summary)

    async def start_from_incident(
        self,
        incident_report: dict,
        tech_lead: str = "tech-lead@company.local",
        session_id: str | None = None,
    ) -> tuple[str, str]:
        """Seed Meridian session from Aegis incident report and generate PRD."""
        session = MeridianSessionStore.get_or_create(session_id)
        prompt = build_incident_prd_prompt(incident_report, tech_lead)
        sid, _, _ = await chat_with_meridian(
            session_id=session.id,
            message=prompt,
            role="incident",
            repo=self._run_repo,
        )
        title = f"Incident Remediation: {incident_report.get('title', 'Unknown')}"
        prd_output = await self.generate_prd(
            session_id=sid,
            title=title,
            stakeholders="Incident Response Team",
            tech_lead=tech_lead,
        )
        return sid, prd_output.run_id
