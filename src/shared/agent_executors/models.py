from enum import StrEnum


class AgentExecutorType(StrEnum):
    CURSOR = "cursor"
    OPENAI = "openai"
    CLAUDE = "claude"


EXECUTOR_LABELS: dict[str, str] = {
    AgentExecutorType.CURSOR: "Cursor (Local SDK / Bridge)",
    AgentExecutorType.OPENAI: "OpenAI API",
    AgentExecutorType.CLAUDE: "Claude (Anthropic API)",
}

ALL_EXECUTOR_TYPES = list(AgentExecutorType)
