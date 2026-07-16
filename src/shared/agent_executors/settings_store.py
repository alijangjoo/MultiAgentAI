import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import get_settings
from shared.agent_executors.models import AgentExecutorType


class AgentExecutorSettings(BaseModel):
    forge_executor: AgentExecutorType = AgentExecutorType.CURSOR
    sentinel_executor: AgentExecutorType = AgentExecutorType.CURSOR
    updated_at: str | None = None
    updated_by: str | None = None


def _settings_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    base = root / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "agent_executor_settings.json"


def _defaults_from_env() -> AgentExecutorSettings:
    settings = get_settings()
    forge = settings.forge_executor.lower()
    sentinel = settings.sentinel_executor.lower()
    return AgentExecutorSettings(
        forge_executor=AgentExecutorType(forge)
        if forge in AgentExecutorType._value2member_map_
        else AgentExecutorType.CURSOR,
        sentinel_executor=AgentExecutorType(sentinel)
        if sentinel in AgentExecutorType._value2member_map_
        else AgentExecutorType.CURSOR,
    )


def get_agent_executor_settings() -> AgentExecutorSettings:
    path = _settings_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return AgentExecutorSettings(**data)
        except Exception:
            pass
    return _defaults_from_env()


def save_agent_executor_settings(
    forge_executor: AgentExecutorType,
    sentinel_executor: AgentExecutorType,
    updated_by: str = "dashboard",
) -> AgentExecutorSettings:
    payload = AgentExecutorSettings(
        forge_executor=forge_executor,
        sentinel_executor=sentinel_executor,
        updated_at=datetime.now(timezone.utc).isoformat(),
        updated_by=updated_by,
    )
    path = _settings_path()
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return payload
