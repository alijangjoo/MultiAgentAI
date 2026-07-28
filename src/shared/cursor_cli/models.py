from typing import Any

from pydantic import BaseModel, Field


class ReviewContext(BaseModel):
    """Structured review payload embedded in the Cursor CLI prompt."""

    title: str | None = Field(default=None, description="PR / change title")
    description: str | None = Field(default=None, description="PR / change description")
    git_diff: str = Field(..., min_length=1, description="Unified git diff to review")
    specs: str | None = Field(default=None, description="Product / technical specs")
    review_rules: str | None = Field(default=None, description="Review rubric / severity rules")
    extra_context: dict[str, Any] | None = Field(
        default=None,
        description="Additional named sections (ADRs, tech stack, etc.)",
    )
    language: str = Field(default="en", description="Review response language (e.g. en, fa)")
    use_review_skill: bool = Field(
        default=False,
        description="When true, prompt instructs Cursor to apply .cursor/skills/sentinel-review",
    )


class ReviewRequest(BaseModel):
    """Cursor CLI review invocation with per-request overrides."""

    context: ReviewContext
    model: str | None = Field(default=None, description="Override review model for this request")
    workspace: str | None = Field(default=None, description="Override --workspace")
    output_format: str | None = Field(
        default=None,
        description="Override output format: text | json | stream-json",
    )
    mode: str | None = Field(default=None, description="Override agent mode: ask | plan | agent")
    timeout_seconds: int | None = Field(default=None, ge=30, le=1800)


class ReviewResponse(BaseModel):
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    prompt_chars: int
    timed_out: bool = False


class CursorCliResult(BaseModel):
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    prompt_chars: int
    timed_out: bool = False
