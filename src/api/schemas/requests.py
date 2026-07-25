from pydantic import BaseModel, Field

from shared.models.domain import HITLAction


class FeaturePipelineRequest(BaseModel):
    task_key: str = Field(..., examples=["VEN-100"])
    subtask_index: int = Field(default=0, ge=0)
    tech_lead_email: str = Field(default="tech-lead@company.local")
    confluence_page_id: str | None = None


class FeaturePipelineResponse(BaseModel):
    run_id: str
    status: str
    task_key: str
    hitl_checkpoint_id: str | None = None
    merge_request_url: str | None = None
    message: str


class HITLResolveRequest(BaseModel):
    action: HITLAction
    resolved_by: str = Field(..., examples=["tech-lead@company.local"])
    comment: str | None = None


class HITLResolveResponse(BaseModel):
    checkpoint_id: str
    run_id: str
    action: HITLAction
    pipeline_status: str
    message: str


class IncidentAnalysisRequest(BaseModel):
    channel_id: str | None = None
    notify_tech_lead: bool = True
    tech_lead_email: str = "tech-lead@company.local"


class IncidentAnalysisResponse(BaseModel):
    run_id: str
    status: str
    report: dict
    message: str


class AgentRunResponse(BaseModel):
    id: str
    workflow_type: str
    agent_name: str
    status: str
    input_payload: dict
    output_payload: dict
    error_message: str | None
    created_at: str
    updated_at: str


class AgentEventResponse(BaseModel):
    id: str
    run_id: str
    agent_name: str
    event_type: str
    message: str
    payload: dict
    created_at: str


class DashboardStatsResponse(BaseModel):
    total_runs: int
    running: int
    waiting_hitl: int
    completed: int
    failed: int
    pending_hitl_checkpoints: int


class IntegrationHealthResponse(BaseModel):
    jira: dict
    gitlab: dict
    all_ok: bool


class JiraIssueResponse(BaseModel):
    key: str
    summary: str
    description: str
    status: str
    issue_type: str
    assignee: str | None = None
    priority: str | None = None
    labels: list[str] = Field(default_factory=list)


class JiraTaskListItem(BaseModel):
    key: str
    summary: str
    status: str
    issue_type: str
    assignee: str | None = None
    priority: str | None = None
    labels: list[str] = Field(default_factory=list)
    updated: str | None = None


class JiraTaskListResponse(BaseModel):
    project_key: str
    count: int
    tasks: list[JiraTaskListItem]


class JiraTaskDetailResponse(BaseModel):
    key: str
    summary: str
    description: str
    status: str
    issue_type: str
    assignee: str | None = None
    reporter: str | None = None
    priority: str | None = None
    labels: list[str] = Field(default_factory=list)
    created: str | None = None
    updated: str | None = None
    attachments: list[dict] = Field(default_factory=list)
    has_prd: bool = False
    prd_preview: str | None = None
    subtasks: list[dict] = Field(default_factory=list)
    jira_url: str | None = None
    suggested_short_description: str = ""
    suggested_branch_name: str = ""
    default_source_branch: str = "develop"


class BranchPreviewResponse(BaseModel):
    branch_name: str
    short_description: str


class CreateBranchRequest(BaseModel):
    short_description: str = Field(..., min_length=3, max_length=80)
    source_branch: str | None = Field(default=None, description="Git ref to branch from")
    branch_name: str | None = Field(
        default=None,
        description="Override full branch name; otherwise auto-generated",
    )


class CreateBranchResponse(BaseModel):
    task_key: str
    branch_name: str
    source_branch: str
    created: bool
    exists: bool = False
    message: str


class StartDevelopmentRequest(BaseModel):
    branch_name: str | None = Field(
        default=None,
        description="Optional — auto-generated as feature/{task-key}-{slug} if omitted",
    )
    short_description: str | None = Field(
        default=None,
        description="Slug for branch, e.g. create-api-for-contract",
    )
    environment: str = Field(default="dev", description="dev | stage | production")
    source_branch: str | None = Field(default=None, description="Defaults to main from deploy settings")
    target_branch: str | None = Field(default=None, description="MR target; defaults per environment")
    create_mr: bool = Field(default=True)
    subtask_index: int = Field(default=0, ge=0)
    tech_lead_email: str = Field(default="tech-lead@company.local")


class DevelopResponse(BaseModel):
    run_id: str
    status: str
    task_key: str
    branch_name: str
    files_changed: list[str] = Field(default_factory=list)
    development_summary: str = ""
    merge_request_url: str | None = None
    merge_request_iid: int | None = None
    target_branch: str | None = None
    message: str


class MergeRequestListItem(BaseModel):
    iid: int
    title: str
    state: str
    source_branch: str
    target_branch: str
    web_url: str
    author: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MergeRequestListResponse(BaseModel):
    count: int
    merge_requests: list[MergeRequestListItem]


class MergeRequestReviewRequest(BaseModel):
    reviewed_by: str = Field(default="tech-lead@company.local")


class MergeRequestReviewResponse(BaseModel):
    run_id: str
    mr_iid: int
    status: str
    merge_request_url: str
    review: dict
    review_prompt: str = ""
    prompt_tokens: int = 0
    message: str
    hitl_checkpoint_id: str | None = None
    note_posted: bool | None = None


class MergeRequestReviewContextResponse(BaseModel):
    mr_iid: int
    task_key: str = ""
    merge_request_url: str = ""
    title: str = ""
    source_branch: str = ""
    target_branch: str = ""
    prompt_chars: int = 0
    prompt_tokens: int = 0
    review_prompt: str
    sections: dict[str, bool] = Field(default_factory=dict)


class MergeRequestLastReviewResponse(BaseModel):
    run_id: str
    mr_iid: int
    status: str
    merge_request_url: str = ""
    review: dict
    review_prompt: str = ""
    prompt_tokens: int = 0
    note_posted: bool | None = None
    created_at: str = ""
    message: str = ""


class MergeRequestByEnvironmentResponse(BaseModel):
    branches: dict[str, str]
    dev: list[dict] = Field(default_factory=list)
    stage: list[dict] = Field(default_factory=list)
    production: list[dict] = Field(default_factory=list)
    errors: list[str] | None = None


class MergeRequestStatusResponse(BaseModel):
    mr_iid: int
    has_conflicts: bool = False
    merge_status: str | None = None
    pipeline_status: str | None = None
    pipeline_id: int | None = None
    pipeline_url: str | None = None
    jira_key: str | None = None
    pending_hitl_id: str | None = None


class MergeRequestMergeRequest(BaseModel):
    merged_by: str = Field(default="tech-lead@company.local")


class MergeRequestMergeResponse(BaseModel):
    mr_iid: int
    state: str | None = None
    merge_commit_sha: str | None = None
    web_url: str | None = None
    message: str


class MeridianChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1)
    role: str = Field(default="stakeholder", description="stakeholder or tech_lead")


class MeridianChatResponse(BaseModel):
    session_id: str
    reply: str
    message_count: int


class MeridianGeneratePRDRequest(BaseModel):
    session_id: str
    title: str | None = None
    stakeholders: str = ""
    tech_lead: str = ""


class MeridianGeneratePRDResponse(BaseModel):
    session_id: str
    run_id: str
    prd_content: str
    message: str


class MeridianCreateJiraRequest(BaseModel):
    session_id: str
    summary: str
    prd_content: str | None = None
    issue_type: str = "Story"
    labels: list[str] = Field(default_factory=lambda: ["meridian-prd"])


class MeridianCreateJiraResponse(BaseModel):
    session_id: str
    jira_key: str
    jira_url: str | None = None
    message: str


class IncidentCreatePRDRequest(BaseModel):
    session_id: str | None = None
    tech_lead: str = "tech-lead@company.local"


class IncidentCreatePRDResponse(BaseModel):
    run_id: str
    session_id: str
    prd_run_id: str
    message: str


class KnowledgeBulkIngestRequest(BaseModel):
    ref: str | None = None
    path: str = ""
    limit: int = Field(default=100, ge=1, le=500)
    query: str | None = None
    space_key: str | None = None


class KnowledgeBulkIngestResponse(BaseModel):
    source: str
    documents_ingested: int
    chunks_created: int
    message: str


class AgentExecutorOption(BaseModel):
    id: str
    label: str


class AgentExecutorSettingsResponse(BaseModel):
    forge_executor: str
    sentinel_executor: str
    updated_at: str | None = None
    updated_by: str | None = None
    options: list[AgentExecutorOption]
    cursor_repo_path: str = ""
    cursor_bridge_url: str = ""
    cursor_model: str = ""


class UpdateAgentExecutorSettingsRequest(BaseModel):
    forge_executor: str = Field(..., examples=["cursor"])
    sentinel_executor: str = Field(..., examples=["cursor"])
    updated_by: str = Field(default="dashboard")


class DeployBranchSettingsResponse(BaseModel):
    dev_target_branch: str
    stage_target_branch: str
    production_target_branch: str
    feature_source_branch: str
    is_automatic_send_message: bool = False
    updated_at: str | None = None
    updated_by: str | None = None


class UpdateDeployBranchSettingsRequest(BaseModel):
    dev_target_branch: str = Field(..., examples=["dev-oms-v2"])
    stage_target_branch: str = Field(..., examples=["stage"])
    production_target_branch: str = Field(..., examples=["main"])
    feature_source_branch: str = Field(default="main")
    is_automatic_send_message: bool = Field(
        default=False,
        description="When true, publish Deploy Request to Mattermost without Tech Lead approval",
    )
    updated_by: str = Field(default="dashboard")


class PipelineVariableItem(BaseModel):
    key: str = Field(..., min_length=1, examples=["ENV"])
    value: str = Field(..., examples=["dev"], description="For bump-version: dev, stg, or prd")


class PipelineListItem(BaseModel):
    id: int
    iid: int
    status: str
    ref: str
    sha: str = ""
    web_url: str
    created_at: str | None = None
    updated_at: str | None = None


class PipelineListResponse(BaseModel):
    count: int
    pipelines: list[PipelineListItem]


class PipelineJobItem(BaseModel):
    id: int
    name: str
    stage: str
    status: str
    web_url: str = ""
    when: str | None = None
    allow_failure: bool = False
    retryable: bool = False


class PipelineJobsResponse(BaseModel):
    pipeline_id: int
    count: int
    jobs: list[PipelineJobItem]


class PlayPipelineJobRequest(BaseModel):
    variables: list[PipelineVariableItem] = Field(
        default_factory=lambda: [PipelineVariableItem(key="ENV", value="dev")],
        description="CI variables; bump-version expects ENV=dev|stg|prd",
    )


class PlayPipelineJobResponse(BaseModel):
    id: int
    name: str
    status: str
    variables: list[PipelineVariableItem] = Field(default_factory=list)
    web_url: str | None = None
    message: str


class DeployRequestResponse(BaseModel):
    id: str
    run_id: str
    hitl_checkpoint_id: str | None = None
    status: str
    mr_iid: int | None = None
    mr_url: str | None = None
    source_branch: str | None = None
    target_branch: str | None = None
    pipeline_id: int | None = None
    pipeline_url: str | None = None
    version: str | None = None
    jira_key: str | None = None
    jira_title: str | None = None
    jira_url: str | None = None
    app_name: str | None = None
    service_name: str | None = None
    endpoints: list[str] = Field(default_factory=list)
    changes_url: str | None = None
    priority: str | None = None
    publish_at: str | None = None
    message_body: str | None = None
    mattermost_response: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UpdateDeployRequestRequest(BaseModel):
    priority: str | None = Field(default=None, examples=["P1"])
    publish_at: str | None = Field(default=None, examples=["2026-07-12 14:00"])
    message_body: str | None = None
    version: str | None = Field(default=None, examples=["v0.173.0-dev"])
    jira_key: str | None = Field(default=None, examples=["VEN-100"])


class AssignDeployJiraRequest(BaseModel):
    jira_key: str = Field(..., min_length=3, examples=["VEN-100"])
