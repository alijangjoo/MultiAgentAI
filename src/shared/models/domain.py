"""Shared domain models used across vertical slices."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentName(StrEnum):
    ATLAS = "atlas"
    FORGE = "forge"
    SENTINEL = "sentinel"
    SCRIBE = "scribe"
    AEGIS = "aegis"
    MERIDIAN = "meridian"
    SAGE = "sage"
    ORCHESTRATOR = "orchestrator"
    DEPLOY = "deploy"


class WorkflowType(StrEnum):
    FEATURE_DEVELOPMENT = "feature_development"
    CODE_DEVELOPMENT = "code_development"
    INCIDENT_RESPONSE = "incident_response"
    KNOWLEDGE_QUERY = "knowledge_query"
    KNOWLEDGE_INGEST = "knowledge_ingest"
    MR_CODE_REVIEW = "mr_code_review"
    PRD_WORKFLOW = "prd_workflow"
    DEPLOY_REQUEST = "deploy_request"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HITL = "waiting_hitl"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HITLAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class SubTask(BaseModel):
    title: str
    description: str
    estimated_hours: float = Field(le=8, description="Max 1 day (8 hours)")
    jira_key: str | None = None


class BranchInfo(BaseModel):
    name: str
    task_key: str
    short_description: str


class MergeRequestInfo(BaseModel):
    iid: int
    url: str
    title: str
    source_branch: str
    target_branch: str


class CodeReviewResult(BaseModel):
    approved: bool
    summary: str
    findings: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class AgentRunEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    agent_name: AgentName
    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HITLCheckpoint(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    checkpoint_name: str
    description: str
    context: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False
    action: HITLAction | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
