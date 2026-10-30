"""QA Agent context and result models."""

from pydantic import BaseModel, Field


class QaContext(BaseModel):
    """Input context for branch QA analysis."""

    branch_name: str
    target_branch: str
    task_key: str | None = None
    title: str | None = None
    git_diff: str
    acceptance_criteria: str | None = None
    feature_brief: str | None = None
    language: str = "fa"
    extra_context: dict[str, str] | None = None


class TestCaseItem(BaseModel):
    id: str
    title: str
    preconditions: str = ""
    steps: list[str] = Field(default_factory=list)
    expected_result: str = ""
    priority: str = "medium"
    type: str = "functional"
    linked_ac: str | None = None


class UseCaseItem(BaseModel):
    id: str
    actor: str
    goal: str
    main_flow: list[str] = Field(default_factory=list)
    alternate_flows: list[str] = Field(default_factory=list)


class AcCoverageItem(BaseModel):
    criterion_id: str
    criterion: str
    status: str
    evidence: str = ""


class QaResult(BaseModel):
    """Structured QA output from the agent."""

    ready: bool = False
    verdict: str = "PENDING"
    summary: str = ""
    test_cases: list[TestCaseItem] = Field(default_factory=list)
    use_cases: list[UseCaseItem] = Field(default_factory=list)
    critical_flows: list[str] = Field(default_factory=list)
    ac_coverage: list[AcCoverageItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    automation_suggestions: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
