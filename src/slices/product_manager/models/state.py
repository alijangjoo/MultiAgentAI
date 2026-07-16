from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class MeridianSession(BaseModel):
    id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    prd_content: str | None = None
    prd_run_id: str | None = None


class MeridianChatOutput(BaseModel):
    session_id: str
    reply: str
    message_count: int


class MeridianPRDOutput(BaseModel):
    session_id: str
    run_id: str
    prd_content: str
    title: str


class MeridianJiraOutput(BaseModel):
    session_id: str
    jira_key: str
    summary: str
