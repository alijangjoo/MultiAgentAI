from pydantic import BaseModel, Field

from shared.models.domain import BranchInfo, CodeReviewResult, MergeRequestInfo, SubTask


class AtlasOutput(BaseModel):
    task_key: str
    issue: dict
    subtasks: list[SubTask]
    branch: BranchInfo | None
    prd_content: str = ""


class ForgeOutput(BaseModel):
    task_key: str
    branch_name: str
    subtask_key: str | None
    files_changed: list[str]
    commit_message: str
    development_summary: str
    merge_request_url: str | None = None
    merge_request_iid: int | None = None
    target_branch: str | None = None


class SentinelOutput(BaseModel):
    merge_request: MergeRequestInfo
    review: CodeReviewResult
    review_prompt: str = ""


class ScribeOutput(BaseModel):
    page_id: str
    page_title: str
    updated: bool


class FeaturePipelineInput(BaseModel):
    task_key: str = Field(..., description="Jira issue key, e.g. VEN-100")
    subtask_index: int = Field(default=0, description="Which subtask Forge should implement")
    branch_name: str | None = Field(
        default=None,
        description="Git branch (auto-generated from task if omitted)",
    )
    short_description: str | None = Field(
        default=None,
        description="Slug for branch name, e.g. create-api-for-contract",
    )
    environment: str = Field(default="dev", description="dev | stage | production")
    source_branch: str | None = Field(default=None, description="Branch to create feature from (default: main)")
    target_branch: str | None = Field(default=None, description="MR target branch (default from deploy settings)")
    create_mr: bool = Field(default=True, description="Create merge request after development")
    tech_lead_email: str = Field(default="tech-lead@company.local")
    confluence_page_id: str | None = Field(default=None, description="Page to update after merge")


class FeaturePipelineState(BaseModel):
    run_id: str
    task_key: str
    status: str = "pending"
    atlas_output: AtlasOutput | None = None
    forge_output: ForgeOutput | None = None
    sentinel_output: SentinelOutput | None = None
    scribe_output: ScribeOutput | None = None
    hitl_checkpoint_id: str | None = None
    error: str | None = None
