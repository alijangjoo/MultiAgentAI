"""Deploy Request domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DeployRequestStatus(StrEnum):
    NEEDS_JIRA = "needs_jira"
    # Successful Stage pipeline discovered — waiting for "Generate Message" click
    PIPELINE_READY = "pipeline_ready"
    PIPELINE_TRIGGERED = "pipeline_triggered"
    WAITING_PIPELINE = "waiting_pipeline"
    DRAFT = "draft"
    WAITING_APPROVAL = "waiting_approval"
    PUBLISHED = "published"
    FAILED = "failed"


class DeployRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    hitl_checkpoint_id: str | None = None
    status: DeployRequestStatus = DeployRequestStatus.NEEDS_JIRA
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


class DeployRequestUpdate(BaseModel):
    jira_key: str | None = None
    priority: str | None = None
    publish_at: str | None = None
    message_body: str | None = None
    version: str | None = None


class AssignJiraRequest(BaseModel):
    jira_key: str = Field(..., min_length=3, examples=["VEN-100"])
