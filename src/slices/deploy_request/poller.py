"""Poll GitLab for fully successful Stage tag pipelines (localhost cannot receive webhooks)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.config import get_settings
from shared.deploy_settings.store import get_deploy_branch_settings
from shared.integrations.registry import get_integrations
from slices.deploy_request.models.state import DeployRequestStatus
from slices.deploy_request.orchestrator import DeployRequestOrchestrator
from slices.deploy_request.pipeline_context import (
    is_stg_version_tag,
    list_stg_tag_pipelines,
    pipeline_fully_succeeded,
)
from slices.deploy_request.repository import DeployRequestRepository

logger = logging.getLogger(__name__)

_poll_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def poll_deploy_requests_once() -> dict[str, Any]:
    """
    Keep Ready filled with up to N newest successful Stage tag pipelines that
    do not already have a Published History row.
    Also upgrades legacy pipeline_ready rows by generating their message.
    """
    settings = get_settings()
    stage = get_deploy_branch_settings().stage_target_branch
    gitlab = get_integrations().gitlab
    orchestrator = DeployRequestOrchestrator()
    repo = DeployRequestRepository()

    scan_limit = max(10, int(settings.deploy_poll_mr_limit))
    max_create = max(1, int(settings.deploy_poll_max_create_per_cycle))
    ready_limit = max(1, int(getattr(settings, "deploy_ready_list_limit", 10) or 10))

    checked = 0
    skipped_incomplete = 0
    skipped_history = 0
    created = 0
    auto_published = 0
    errors: list[str] = []

    try:
        pipes = await list_stg_tag_pipelines(gitlab, scan_limit)
    except Exception as exc:
        logger.exception("Deploy poll: list tag pipelines failed")
        return {
            "ok": False,
            "stage_branch": stage,
            "pipelines_checked": 0,
            "skipped_incomplete": 0,
            "skipped_history": 0,
            "created": 0,
            "auto_published": 0,
            "ready_limit": ready_limit,
            "errors": [f"list_pipelines: {exc}"],
        }

    actions = 0
    for pipe in pipes:
        if actions >= max_create:
            break
        checked += 1
        pid = pipe.get("id")
        if pid is None:
            continue
        pid_i = int(pid)

        existing = await repo.get_by_pipeline_id(pid_i)
        if existing and existing.status == DeployRequestStatus.PUBLISHED:
            skipped_history += 1
            continue

        if existing:
            # Already tracked and not published — already visible in Ready; skip re-create
            continue

        ok, jobs, detail = await pipeline_fully_succeeded(gitlab, pid_i)
        if not ok:
            skipped_incomplete += 1
            continue

        ref = (detail or pipe).get("ref") or pipe.get("ref") or stage
        if not is_stg_version_tag(ref):
            skipped_incomplete += 1
            continue

        try:
            req = await orchestrator.register_stage_pipeline(
                pipeline_id=pid_i,
                pipeline_url=(detail or pipe).get("web_url") or pipe.get("web_url"),
                ref=ref,
                sha=(detail or pipe).get("sha") or pipe.get("sha"),
                jobs=jobs,
            )
            created += 1
            actions += 1
            if req.status == DeployRequestStatus.PUBLISHED:
                auto_published += 1
        except Exception as exc:
            logger.exception("Deploy poll: register_stage_pipeline failed for %s", pid_i)
            errors.append(f"pipeline {pid_i}: {exc}")

    return {
        "ok": len(errors) == 0,
        "stage_branch": stage,
        "pipelines_checked": checked,
        "skipped_incomplete": skipped_incomplete,
        "skipped_history": skipped_history,
        "created": created,
        "auto_published": auto_published,
        "ready_limit": ready_limit,
        "scan_limit": scan_limit,
        "merged_checked": 0,
        "pipelines_advanced": 0,
        "errors": errors,
    }


async def _poll_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(15, int(settings.deploy_poll_interval_seconds))
    logger.info(
        "Deploy GitLab poller started (every %ss, scan=%s, max_create=%s, ready_limit=%s)",
        interval,
        settings.deploy_poll_mr_limit,
        settings.deploy_poll_max_create_per_cycle,
        getattr(settings, "deploy_ready_list_limit", 10),
    )
    while not stop_event.is_set():
        try:
            result = await poll_deploy_requests_once()
            if result.get("created") or result.get("auto_published"):
                logger.info("Deploy poll result: %s", result)
            elif result.get("errors"):
                logger.warning("Deploy poll errors: %s", result["errors"])
        except Exception:
            logger.exception("Deploy poll loop iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue
    logger.info("Deploy GitLab poller stopped")


def start_deploy_poller() -> None:
    global _poll_task, _stop_event
    settings = get_settings()
    if not settings.deploy_poll_enabled:
        logger.info("Deploy GitLab poller disabled (DEPLOY_POLL_ENABLED=false)")
        return
    if _poll_task and not _poll_task.done():
        return
    _stop_event = asyncio.Event()
    _poll_task = asyncio.create_task(_poll_loop(_stop_event), name="deploy-gitlab-poller")


async def stop_deploy_poller() -> None:
    global _poll_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _poll_task:
        try:
            await asyncio.wait_for(_poll_task, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _poll_task.cancel()
        _poll_task = None
    _stop_event = None
