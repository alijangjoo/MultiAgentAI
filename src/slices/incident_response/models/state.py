from pydantic import BaseModel, Field


class IncidentReport(BaseModel):
    severity: str
    title: str
    summary: str
    root_cause_hypothesis: str
    affected_services: list[str] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    mattermost_posts_count: int = 0
    logs_analyzed: int = 0
    is_vendor_related: bool = False
    elastic_log_snippets: list[str] = Field(default_factory=list)
    suggested_jira_summary: str = ""
    suggested_jira_description: str = ""


class AegisOutput(BaseModel):
    channel_id: str
    report: IncidentReport
    posts_analyzed: int
    logs_found: int


class IncidentAnalysisInput(BaseModel):
    channel_id: str | None = Field(
        default=None,
        description="Mattermost channel ID. Defaults to DISASTER channel from config.",
    )
    notify_tech_lead: bool = Field(default=True)
    tech_lead_email: str = Field(default="tech-lead@company.local")
