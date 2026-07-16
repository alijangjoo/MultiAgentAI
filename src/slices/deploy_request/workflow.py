"""LangGraph workflow for Stage Deploy Request preparation."""

from __future__ import annotations

import re
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from datetime import datetime

from core.config import get_settings
from shared.deploy_settings.store import is_automatic_send_enabled
from shared.integrations.factory import IntegrationContainer
from shared.models.domain import AgentName, HITLCheckpoint, RunStatus
from shared.persistence.repository import AgentRunRepository, HITLRepository
from shared.utils.endpoints_scanner import list_endpoint_projects
from shared.utils.jira_key_from_branch import extract_jira_key_from_branch
from shared.utils.priority_map import jira_priority_to_pn
from slices.deploy_request.mattermost_webhook import post_deploy_webhook
from slices.deploy_request.message_builder import build_deploy_message
from slices.deploy_request.models.state import DeployRequestStatus
from slices.deploy_request.repository import DeployRequestRepository

_VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+(?:-[\w.]+)?", re.IGNORECASE)


class DeployGraphState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    request_id: str
    run_id: str
    source_branch: str
    target_branch: str
    mr_iid: int | None
    mr_url: str | None
    pipeline_id: int | None
    pipeline_url: str | None
    jira_key: str | None
    version: str | None
    needs_jira: bool
    status: str
    error: str | None


def _project_display_name() -> str:
    settings = get_settings()
    path = settings.gitlab_project_path or ""
    if path:
        return path.rstrip("/").split("/")[-1].capitalize() or "Dizi"
    return "Dizi"


def _changes_url(mr_url: str | None) -> str | None:
    if not mr_url:
        return None
    base = mr_url.rstrip("/")
    if base.endswith("/diffs"):
        return base
    return f"{base}/diffs"


def _jira_browse_url(jira_key: str) -> str:
    settings = get_settings()
    base = (settings.jira_url or "https://desk.tapsifood.cloud").rstrip("/")
    return f"{base}/browse/{jira_key.upper()}"


async def extract_jira_node(state: DeployGraphState, repo: AgentRunRepository) -> dict:
    jira_key = state.get("jira_key") or extract_jira_key_from_branch(state.get("source_branch"))
    await repo.log_event_by_type(
        state["run_id"],
        AgentName.DEPLOY,
        "jira_extract",
        f"Extracted jira_key={jira_key or 'none'} from {state.get('source_branch')}",
    )
    return {
        "jira_key": jira_key,
        "needs_jira": jira_key is None,
        "status": (
            DeployRequestStatus.NEEDS_JIRA.value
            if jira_key is None
            else DeployRequestStatus.PIPELINE_TRIGGERED.value
        ),
    }


async def trigger_stg_pipeline_node(
    state: DeployGraphState,
    integrations: IntegrationContainer,
    deploy_repo: DeployRequestRepository,
    run_repo: AgentRunRepository,
) -> dict:
    settings = get_settings()
    ref = state.get("target_branch") or settings.gitlab_mr_target_stage
    variables = [{"key": "ENV", "value": "stg"}]
    gitlab = integrations.gitlab

    try:
        if not hasattr(gitlab, "create_pipeline"):
            raise NotImplementedError("GitLab create_pipeline is not available")
        pipeline = await gitlab.create_pipeline(ref=ref, variables=variables)
        pipeline_id = pipeline.get("id")
        pipeline_url = pipeline.get("web_url")

        # Prefer playing bump-version with ENV=stg when a manual job appears.
        if pipeline_id and hasattr(gitlab, "list_pipeline_jobs") and hasattr(gitlab, "play_job"):
            try:
                jobs = await gitlab.list_pipeline_jobs(pipeline_id)
                bump = next(
                    (
                        j
                        for j in jobs
                        if j.get("name") == "bump-version" and j.get("status") == "manual"
                    ),
                    None,
                )
                if bump:
                    await gitlab.play_job(bump["id"], variables)
            except Exception:
                pass

        await deploy_repo.update_fields(
            state["request_id"],
            status=DeployRequestStatus.WAITING_PIPELINE,
            pipeline_id=pipeline_id,
            pipeline_url=pipeline_url,
            jira_key=state.get("jira_key"),
            error_message=None,
        )
        await run_repo.log_event_by_type(
            state["run_id"],
            AgentName.DEPLOY,
            "pipeline_triggered",
            f"Triggered pipeline {pipeline_id} on {ref} with ENV=stg",
            {"pipeline_id": pipeline_id, "ref": ref},
        )
        return {
            "pipeline_id": pipeline_id,
            "pipeline_url": pipeline_url,
            "status": DeployRequestStatus.WAITING_PIPELINE.value,
            "error": None,
        }
    except Exception as exc:
        await deploy_repo.update_fields(
            state["request_id"],
            status=DeployRequestStatus.FAILED,
            error_message=str(exc),
        )
        await run_repo.log_event_by_type(
            state["run_id"],
            AgentName.DEPLOY,
            "pipeline_trigger_failed",
            str(exc),
        )
        return {"status": DeployRequestStatus.FAILED.value, "error": str(exc)}


async def enrich_message_node(
    state: DeployGraphState,
    integrations: IntegrationContainer,
    deploy_repo: DeployRequestRepository,
    run_repo: AgentRunRepository,
) -> dict:
    req = await deploy_repo.get(state["request_id"])
    if not req:
        return {"error": "Deploy request not found", "status": DeployRequestStatus.FAILED.value}

    jira_key = (state.get("jira_key") or req.jira_key or "").upper() or None
    jira_title = req.jira_title
    priority = req.priority
    jira_url = req.jira_url

    if jira_key:
        jira_url = _jira_browse_url(jira_key)
        try:
            issue = await integrations.jira.get_issue(jira_key)
            jira_title = issue.get("summary") or jira_title
            # Always refresh Priority from Jira on Generate Message
            mapped = jira_priority_to_pn(issue.get("priority"))
            if mapped:
                priority = mapped
        except Exception as exc:
            await run_repo.log_event_by_type(
                state["run_id"],
                AgentName.DEPLOY,
                "jira_fetch_warning",
                f"Could not load Jira {jira_key}: {exc}",
            )

    app_name = req.app_name or _project_display_name()
    service_name = req.service_name or f"{app_name} service"
    endpoints = req.endpoints or list_endpoint_projects() or ["dizi api"]
    # Prefer commit URL (stored on register); fall back to MR diffs
    changes_url = req.changes_url or _changes_url(req.mr_url)
    pipeline_url = state.get("pipeline_url") or req.pipeline_url
    version = state.get("version") or req.version
    pipeline_id = state.get("pipeline_id") or req.pipeline_id

    # Version from pipeline tag/ref (e.g. For v2.307.0-stg), then job names
    if pipeline_id and hasattr(integrations.gitlab, "get_pipeline"):
        try:
            from slices.deploy_request.pipeline_context import extract_version_from_jobs

            pipe = await integrations.gitlab.get_pipeline(int(pipeline_id))
            pipeline_url = pipeline_url or pipe.get("web_url")
            jobs: list = []
            if hasattr(integrations.gitlab, "list_pipeline_jobs"):
                jobs = await integrations.gitlab.list_pipeline_jobs(int(pipeline_id))
            tag_version = extract_version_from_jobs(jobs, pipe.get("ref"))
            if tag_version:
                version = tag_version
        except Exception as exc:
            await run_repo.log_event_by_type(
                state["run_id"],
                AgentName.DEPLOY,
                "version_extract_warning",
                f"Could not resolve pipeline tag/version: {exc}",
            )
    elif not version and pipeline_id and hasattr(integrations.gitlab, "list_pipeline_jobs"):
        try:
            from slices.deploy_request.pipeline_context import extract_version_from_jobs

            jobs = await integrations.gitlab.list_pipeline_jobs(int(pipeline_id))
            version = extract_version_from_jobs(jobs, state.get("target_branch"))
        except Exception:
            pass

    if jira_key and not jira_url:
        jira_url = _jira_browse_url(jira_key)

    updated = await deploy_repo.update_fields(
        req.id,
        jira_key=jira_key,
        jira_title=jira_title,
        jira_url=jira_url,
        priority=priority,
        app_name=app_name,
        service_name=service_name,
        endpoints=endpoints,
        changes_url=changes_url,
        pipeline_id=state.get("pipeline_id") or req.pipeline_id,
        pipeline_url=pipeline_url,
        version=version,
        status=DeployRequestStatus.DRAFT,
        error_message=None,
    )
    assert updated is not None
    message = build_deploy_message(updated)
    await deploy_repo.update_fields(req.id, message_body=message)

    await run_repo.log_event_by_type(
        state["run_id"],
        AgentName.DEPLOY,
        "message_enriched",
        f"Draft deploy message ready for {jira_key or 'unknown'}",
    )
    return {
        "jira_key": jira_key,
        "status": DeployRequestStatus.DRAFT.value,
        "pipeline_url": pipeline_url,
        "error": None,
    }


async def create_hitl_node(
    state: DeployGraphState,
    deploy_repo: DeployRequestRepository,
    hitl_repo: HITLRepository,
    run_repo: AgentRunRepository,
) -> dict:
    req = await deploy_repo.get(state["request_id"])
    if not req:
        return {"error": "Deploy request not found", "status": DeployRequestStatus.FAILED.value}

    checkpoint = HITLCheckpoint(
        run_id=state["run_id"],
        checkpoint_name="deploy_request_approval",
        description=(
            f"Review and approve Deploy Request for "
            f"{req.jira_key or req.source_branch or req.id} before Mattermost publish"
        ),
        context={
            "deploy_request_id": req.id,
            "jira_key": req.jira_key,
            "mr_iid": req.mr_iid,
            "pipeline_id": req.pipeline_id,
        },
    )
    await hitl_repo.create_checkpoint(checkpoint)
    await deploy_repo.update_fields(
        req.id,
        hitl_checkpoint_id=checkpoint.id,
        status=DeployRequestStatus.WAITING_APPROVAL,
        message_body=req.message_body or build_deploy_message(req),
    )
    await run_repo.log_event_by_type(
        state["run_id"],
        AgentName.DEPLOY,
        "waiting_hitl",
        f"HITL checkpoint {checkpoint.id} created",
    )
    return {
        "status": DeployRequestStatus.WAITING_APPROVAL.value,
        "error": None,
    }


async def maybe_auto_publish_node(
    state: DeployGraphState,
    deploy_repo: DeployRequestRepository,
    hitl_repo: HITLRepository,
    run_repo: AgentRunRepository,
    *,
    force_auto_send: bool = False,
) -> dict:
    """If IsAutomaticSendMessage is on, publish to Mattermost; otherwise create HITL."""
    if state.get("error") or state.get("status") == DeployRequestStatus.FAILED.value:
        return {"status": DeployRequestStatus.FAILED.value}

    auto = force_auto_send or is_automatic_send_enabled()
    if not auto:
        return await create_hitl_node(state, deploy_repo, hitl_repo, run_repo)

    req = await deploy_repo.get(state["request_id"])
    if not req:
        return {"error": "Deploy request not found", "status": DeployRequestStatus.FAILED.value}

    publish_at = req.publish_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    priority = req.priority or "P2"
    updated = await deploy_repo.update_fields(
        req.id,
        publish_at=publish_at,
        priority=priority,
    )
    assert updated is not None
    message = build_deploy_message(updated)
    try:
        response = await post_deploy_webhook(message)
        await deploy_repo.update_fields(
            req.id,
            status=DeployRequestStatus.PUBLISHED,
            message_body=message,
            mattermost_response=str(response),
            error_message=None,
        )
        await run_repo.update_run(
            state["run_id"],
            status=RunStatus.COMPLETED,
            output_payload={
                "deploy_request_id": req.id,
                "status": DeployRequestStatus.PUBLISHED.value,
                "published_by": "auto",
                "mattermost": response,
            },
        )
        await run_repo.log_event_by_type(
            state["run_id"],
            AgentName.DEPLOY,
            "auto_published",
            "Deploy Request auto-published to Mattermost (IsAutomaticSendMessage=true)",
        )
        return {"status": DeployRequestStatus.PUBLISHED.value, "error": None}
    except Exception as exc:
        # Fall back to manual approval if webhook fails
        await deploy_repo.update_fields(
            req.id,
            error_message=f"Auto-send failed: {exc}",
            message_body=message,
        )
        await run_repo.log_event_by_type(
            state["run_id"],
            AgentName.DEPLOY,
            "auto_publish_failed",
            str(exc),
        )
        return await create_hitl_node(state, deploy_repo, hitl_repo, run_repo)


def route_after_extract(state: DeployGraphState) -> str:
    if state.get("needs_jira"):
        return "needs_jira"
    return "trigger"


def build_merge_graph(
    integrations: IntegrationContainer,
    run_repo: AgentRunRepository,
    deploy_repo: DeployRequestRepository,
) -> Any:
    graph = StateGraph(DeployGraphState)

    async def extract_node(state: DeployGraphState) -> dict:
        return await extract_jira_node(state, run_repo)

    async def trigger_node(state: DeployGraphState) -> dict:
        return await trigger_stg_pipeline_node(state, integrations, deploy_repo, run_repo)

    async def mark_needs_jira(state: DeployGraphState) -> dict:
        await deploy_repo.update_fields(
            state["request_id"],
            status=DeployRequestStatus.NEEDS_JIRA,
            jira_key=None,
            error_message="Could not extract Jira key from branch name",
        )
        await run_repo.log_event_by_type(
            state["run_id"],
            AgentName.DEPLOY,
            "needs_jira",
            f"Branch {state.get('source_branch')} has no Jira key",
        )
        return {"status": DeployRequestStatus.NEEDS_JIRA.value}

    graph.add_node("extract_jira", extract_node)
    graph.add_node("trigger_pipeline", trigger_node)
    graph.add_node("needs_jira", mark_needs_jira)
    graph.set_entry_point("extract_jira")
    graph.add_conditional_edges(
        "extract_jira",
        route_after_extract,
        {"needs_jira": "needs_jira", "trigger": "trigger_pipeline"},
    )
    graph.add_edge("needs_jira", END)
    graph.add_edge("trigger_pipeline", END)
    return graph.compile()


def build_enrich_graph(
    integrations: IntegrationContainer,
    run_repo: AgentRunRepository,
    deploy_repo: DeployRequestRepository,
    hitl_repo: HITLRepository,
    *,
    force_auto_send: bool = False,
) -> Any:
    graph = StateGraph(DeployGraphState)

    async def enrich_node(state: DeployGraphState) -> dict:
        return await enrich_message_node(state, integrations, deploy_repo, run_repo)

    async def hitl_or_auto_node(state: DeployGraphState) -> dict:
        return await maybe_auto_publish_node(
            state,
            deploy_repo,
            hitl_repo,
            run_repo,
            force_auto_send=force_auto_send,
        )

    graph.add_node("enrich", enrich_node)
    graph.add_node("create_hitl", hitl_or_auto_node)
    graph.set_entry_point("enrich")
    graph.add_edge("enrich", "create_hitl")
    graph.add_edge("create_hitl", END)
    return graph.compile()
