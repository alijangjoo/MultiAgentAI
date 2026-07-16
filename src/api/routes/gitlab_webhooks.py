"""GitLab webhook endpoints for Stage Deploy Request flow."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from core.config import get_settings
from shared.deploy_settings.store import get_deploy_branch_settings
from slices.deploy_request.orchestrator import DeployRequestOrchestrator
from slices.deploy_request.pipeline_context import is_stg_version_tag, normalize_version_tag

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def _get_orchestrator() -> DeployRequestOrchestrator:
    return DeployRequestOrchestrator()


def _verify_token(token: str | None) -> None:
    settings = get_settings()
    expected = (settings.gitlab_webhook_secret or "").strip()
    if not expected:
        return
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid GitLab webhook token")


def _pipeline_variables(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("variables") or []
    out: dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("key"):
                out[str(item["key"])] = str(item.get("value", ""))
    elif isinstance(raw, dict):
        out = {str(k): str(v) for k, v in raw.items()}
    return out


def _extract_version(payload: dict[str, Any]) -> str | None:
    for key in ("tag", "ref"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("v") and any(c.isdigit() for c in value):
            return value
    commit = payload.get("commit") or {}
    message = commit.get("message") or ""
    if isinstance(message, str) and "v" in message.lower():
        import re

        match = re.search(r"v?\d+\.\d+\.\d+(?:-[\w.]+)?", message, re.IGNORECASE)
        if match:
            ver = match.group(0)
            return ver if ver.startswith("v") else f"v{ver}"
    return None


@router.post("/gitlab")
async def gitlab_webhook(
    request: Request,
    x_gitlab_token: str | None = Header(default=None, alias="X-Gitlab-Token"),
    x_gitlab_event: str | None = Header(default=None, alias="X-Gitlab-Event"),
):
    _verify_token(x_gitlab_token)
    payload = await request.json()
    object_kind = (payload.get("object_kind") or "").lower()
    event = (x_gitlab_event or object_kind or "").lower()
    orchestrator = _get_orchestrator()
    stage = get_deploy_branch_settings().stage_target_branch

    # Deploy Request is pipeline-driven now; MR merge alone does not create a request.
    if object_kind == "merge_request" or "merge request" in event:
        return {
            "handled": False,
            "reason": (
                "Deploy Request waits for a successful Stage pipeline "
                "(bump-version ENV=stg), not MR merge alone"
            ),
        }

    if object_kind == "pipeline" or "pipeline" in event:
        attrs = payload.get("object_attributes") or payload
        status = (attrs.get("status") or "").lower()
        if status != "success":
            return {"handled": False, "reason": f"pipeline status={status}"}

        ref = attrs.get("ref")
        variables = _pipeline_variables(payload)
        if "ENV" not in variables and "env" not in variables:
            for build in payload.get("builds") or []:
                for var in build.get("variables") or []:
                    if isinstance(var, dict) and var.get("key"):
                        variables[str(var["key"])] = str(var.get("value", ""))

        env = variables.get("ENV") or variables.get("env")
        is_stg_tag = is_stg_version_tag(ref)
        if env and env.lower() not in ("stg", "stage", "staging") and not is_stg_tag:
            return {"handled": False, "reason": f"ENV={env} is not stg"}
        if (
            ref
            and ref != stage
            and not is_stg_tag
            and not (env and env.lower() in ("stg", "stage", "staging"))
        ):
            return {"handled": False, "reason": f"ref {ref} is not stage/stg-tag and ENV missing"}

        commit = payload.get("commit") or {}
        sha = attrs.get("sha") or commit.get("id")
        version = normalize_version_tag(ref) or _extract_version(payload)

        req = await orchestrator.handle_pipeline_success(
            pipeline_id=int(attrs.get("id")),
            pipeline_url=attrs.get("url") or attrs.get("web_url"),
            ref=ref,
            variables=variables or ({"ENV": "stg"} if is_stg_tag or ref == stage else {}),
            version=version,
            sha=sha,
        )
        if not req:
            return {"handled": False, "reason": "pipeline not registered"}
        return {
            "handled": True,
            "type": "pipeline",
            "deploy_request_id": req.id,
            "status": req.status.value,
            "hitl_checkpoint_id": req.hitl_checkpoint_id,
        }

    return {"handled": False, "reason": f"unsupported event {object_kind or event}"}
