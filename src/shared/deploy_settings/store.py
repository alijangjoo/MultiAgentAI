"""Persist MR target branches per deployment environment (dev/stage/production)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import get_settings

SETTINGS_PATH = Path("./data/deploy_settings.json")


class DeployEnvironment(StrEnum):
    DEV = "dev"
    STAGE = "stage"
    PRODUCTION = "production"


class DeployBranchSettings(BaseModel):
    dev_target_branch: str = "dev-oms-v2"
    stage_target_branch: str = "stage"
    production_target_branch: str = "main"
    feature_source_branch: str = "main"
    # When true, Mattermost publish skips Tech Lead approval (default false)
    is_automatic_send_message: bool = False
    updated_at: str | None = None
    updated_by: str | None = None


def _defaults_from_env() -> DeployBranchSettings:
    s = get_settings()
    return DeployBranchSettings(
        dev_target_branch=s.gitlab_mr_target_dev,
        stage_target_branch=s.gitlab_mr_target_stage,
        production_target_branch=s.gitlab_mr_target_production,
        feature_source_branch=s.gitlab_feature_source_branch,
        is_automatic_send_message=bool(s.deploy_is_automatic_send_message),
    )


def is_automatic_send_enabled() -> bool:
    """Dashboard setting takes precedence over env default once saved."""
    cfg = get_deploy_branch_settings()
    if SETTINGS_PATH.exists():
        return bool(cfg.is_automatic_send_message)
    return bool(get_settings().deploy_is_automatic_send_message)


def get_deploy_branch_settings() -> DeployBranchSettings:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return DeployBranchSettings(**data)
        except Exception:
            pass
    return _defaults_from_env()


def save_deploy_branch_settings(settings: DeployBranchSettings) -> DeployBranchSettings:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.updated_at = datetime.now(timezone.utc).isoformat()
    SETTINGS_PATH.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    return settings


def resolve_target_branch(environment: str, override: str | None = None) -> str:
    if override:
        return override
    cfg = get_deploy_branch_settings()
    env = environment.lower()
    if env == DeployEnvironment.STAGE:
        return cfg.stage_target_branch
    if env in (DeployEnvironment.PRODUCTION, "prod"):
        return cfg.production_target_branch
    return cfg.dev_target_branch


def resolve_source_branch(override: str | None = None) -> str:
    if override:
        return override
    return get_deploy_branch_settings().feature_source_branch
