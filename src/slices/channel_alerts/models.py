"""Incoming Disaster / Bugs messages and vendor classification."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IncomingAlert(BaseModel):
    external_id: str
    list_name: str
    channel_id: str = ""
    channel_name: str = ""
    user_name: str = ""
    text: str


class Classification(BaseModel):
    vendor_related: bool = False
    vendor_name: str = ""
    reason: str = ""
    confidence: float = 0.0
    classifier: str = ""
    knowledge_hits: list[str] = Field(default_factory=list)
    status: str = "done"


class ChannelAlert(BaseModel):
    id: str
    external_id: str
    list_name: str
    channel_id: str = ""
    channel_name: str = ""
    user_name: str = ""
    text: str
    vendor_related: bool = False
    vendor_name: str = ""
    vendor_reason: str = ""
    confidence: float = 0.0
    classifier: str = ""
    classification_status: str = "pending"
    knowledge_hits: list[str] = Field(default_factory=list)
    created_at: str | None = None