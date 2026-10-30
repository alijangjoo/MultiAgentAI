"""Orchestrates Stage Deploy Request flow (successful Stage pipeline → message → Mattermost)."""

from __future__ import annotations

from typing import Any

from core.tracing import trace_config
from shared.deploy_settings.store import get_deploy_branch_settings, is_automatic_send_enabled
from shared.integrations.factory import IntegrationContainer
from shared.integrations.registry import get_integrations
from shared.models.domain import AgentName, HITLAction, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository, HITLRepository
from shared.utils.jira_key_from_branch import extract_jira_key_from_branch
from shared.utils.priority_map import jira_priority_to_pn
from slices.deploy_request.mattermost_webhook import post_deploy_webhook
from slices.deploy_request.message_builder import build_deploy_message
from slices.deploy_request.models.state import DeployRequest, DeployRequestStatus
from slices.deploy_request.pipeline_context import (
    all_required_jobs_succeeded,
    commit_changes_url,
    context_from_mr,
    deploy_target_branch_for_ref,
    extract_version_from_jobs,
    find_related_merged_mr,
    is_deploy_pipeline_ref,
    is_stg_version_tag,
    list_deploy_pipelines,
    normalize_version_tag,
    pipeline_fully_succeeded,
)
from slices.deploy_request.repository import DeployRequestRepository
from slices.deploy_request.workflow import (
    _jira_browse_url,
    _project_display_name,
    build_enrich_graph,
)


class DeployRequestOrchestrator:
    def __init__(
        self,
        integrations: IntegrationContainer | None = None,
        run_repo: AgentRunRepository | None = None,
        hitl_repo: HITLRepository | None = None,
        deploy_repo: DeployRequestRepository | None = None,
    ):
        self._integrations = integrations or get_integrations()
        self._run_repo = run_repo or AgentRunRepository()
        self._hitl_repo = hitl_repo or HITLRepository()
        self._deploy_repo = deploy_repo or DeployRequestRepository()

    def _stage_branch(self) -> str:
        return get_deploy_branch_settings().stage_target_branch

    async def register_stage_pipeline(
        self,
        *,
        pipeline_id: int,
        pipeline_url: str | None,
        ref: str | None,
        sha: str | None = None,
        jobs: list[dict[str, Any]] | None = None,
        version: str | None = None,
        mr_iid: int | None = None,
        mr_url: str | None = None,
        source_branch: str | None = None,
        force: bool = False,
    ) -> DeployRequest:
        """
        Register a successful Stage pipeline as PIPELINE_READY.
        If IsAutomaticSendMessage is on → generate + publish immediately.
        """
        cfg = get_deploy_branch_settings()
        stage = cfg.stage_target_branch
        production = cfg.production_target_branch
        if ref and not is_deploy_pipeline_ref(
            ref, stage_branch=stage, production_branch=production
        ) and not normalize_version_tag(ref):
            raise ValueError(
                f"Pipeline ref {ref!r} is not a deploy ref "
                f"(Stage tag, {stage!r}, or {production!r})"
            )
        mr_target = deploy_target_branch_for_ref(
            ref, stage_branch=stage, production_branch=production
        )

        existing = await self._deploy_repo.get_by_pipeline_id(pipeline_id)
        if existing and existing.status != DeployRequestStatus.FAILED:
            return existing
        if existing and existing.status == DeployRequestStatus.FAILED and not force:
            return existing

        gitlab = self._integrations.gitlab
        if jobs is None and hasattr(gitlab, "list_pipeline_jobs"):
            try:
                jobs = await gitlab.list_pipeline_jobs(pipeline_id)
            except Exception:
                jobs = []
        jobs = jobs or []
        pipe_status: str | None = None
        if hasattr(gitlab, "get_pipeline"):
            try:
                pipe_detail = await gitlab.get_pipeline(pipeline_id)
                pipe_status = pipe_detail.get("status")
            except Exception:
                pipe_status = None
        if not jobs and (pipe_status or "").lower() != "success":
            raise ValueError(
                f"Pipeline {pipeline_id} is not fully successful yet "
                "(all required jobs must finish with success)"
            )
        if jobs and not all_required_jobs_succeeded(jobs, pipeline_status=pipe_status):
            if (pipe_status or "").lower() != "success":
                raise ValueError(
                    f"Pipeline {pipeline_id} is not fully successful yet "
                    "(all required jobs must finish with success)"
                )

        # Tag pipeline ref is the version (GitLab shows "For v2.307.0-stg")
        resolved_version = (
            version
            or normalize_version_tag(ref)
            or extract_version_from_jobs(jobs, ref)
        )

        mr_ctx: dict[str, Any] = {
            "mr_iid": mr_iid,
            "mr_url": mr_url,
            "source_branch": source_branch,
            "jira_key": extract_jira_key_from_branch(source_branch) if source_branch else None,
        }
        if mr_iid is None:
            mr = await find_related_merged_mr(
                gitlab, target_branch=mr_target, sha=sha
            )
            mr_ctx = context_from_mr(mr)
            if mr and not sha:
                sha = mr.get("merge_commit_sha") or mr.get("sha")

        changes_url = commit_changes_url(
            sha,
            pipeline_url=pipeline_url,
            mr_url=mr_ctx.get("mr_url"),
        )

        app_name = _project_display_name()
        jira_key = mr_ctx.get("jira_key")
        initial_status = (
            DeployRequestStatus.NEEDS_JIRA
            if not jira_key
            else DeployRequestStatus.PIPELINE_READY
        )

        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.DEPLOY_REQUEST.value,
            agent_name=AgentName.DEPLOY,
            input_payload={
                "pipeline_id": pipeline_id,
                "ref": ref or stage,
                "sha": sha,
                "mr_iid": mr_ctx.get("mr_iid"),
                "source_branch": mr_ctx.get("source_branch"),
            },
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        req = DeployRequest(
            run_id=run_id,
            status=initial_status,
            mr_iid=mr_ctx.get("mr_iid"),
            mr_url=mr_ctx.get("mr_url"),
            source_branch=mr_ctx.get("source_branch"),
            target_branch=mr_target,
            pipeline_id=pipeline_id,
            pipeline_url=pipeline_url,
            version=resolved_version,
            jira_key=jira_key,
            jira_url=_jira_browse_url(jira_key) if jira_key else None,
            app_name=app_name,
            service_name=f"{app_name} service",
            endpoints=["dizi api"],
            changes_url=changes_url,
            error_message=(
                "Could not extract Jira key from related branch — assign on dashboard"
                if initial_status == DeployRequestStatus.NEEDS_JIRA
                else None
            ),
        )
        await self._deploy_repo.create(req)
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.DEPLOY,
            "pipeline_ready",
            f"Registered successful Stage pipeline {pipeline_id}",
            {"pipeline_id": pipeline_id, "version": resolved_version, "jira_key": jira_key},
        )

        # Auto-send: generate + Mattermost. Otherwise leave as pipeline_ready (Success in Ready list).
        if is_automatic_send_enabled() and jira_key:
            return await self.generate_message(req.id, auto_from_pipeline=True)

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.WAITING_HITL
            if initial_status == DeployRequestStatus.NEEDS_JIRA
            else RunStatus.RUNNING,
            output_payload={
                "deploy_request_id": req.id,
                "status": initial_status.value,
                "pipeline_id": pipeline_id,
            },
        )
        updated = await self._deploy_repo.get(req.id)
        assert updated is not None
        return updated

    async def generate_message(
        self,
        request_id: str,
        *,
        auto_from_pipeline: bool = False,
    ) -> DeployRequest:
        """Build Deploy Request message (dashboard click, or auto-send path)."""
        req = await self._deploy_repo.get(request_id)
        if not req:
            raise ValueError("Deploy request not found")
        if req.status == DeployRequestStatus.PUBLISHED:
            return req
        if req.status not in (
            DeployRequestStatus.PIPELINE_READY,
            DeployRequestStatus.NEEDS_JIRA,
            DeployRequestStatus.DRAFT,
            DeployRequestStatus.WAITING_APPROVAL,
            DeployRequestStatus.FAILED,
        ):
            raise ValueError(f"Cannot generate message in status={req.status.value}")

        # Re-verify every job finished successfully before building the message
        if req.pipeline_id and hasattr(self._integrations.gitlab, "list_pipeline_jobs"):
            try:
                pipe = None
                if hasattr(self._integrations.gitlab, "get_pipeline"):
                    pipe = await self._integrations.gitlab.get_pipeline(int(req.pipeline_id))
                if pipe and (pipe.get("status") or "").lower() != "success":
                    raise ValueError(
                        f"Pipeline {req.pipeline_id} status is {pipe.get('status')!r}, not success"
                    )
                jobs = await self._integrations.gitlab.list_pipeline_jobs(int(req.pipeline_id))
                pipe_st = pipe.get("status") if pipe else None
                if not all_required_jobs_succeeded(jobs, pipeline_status=pipe_st):
                    if (pipe_st or "").lower() != "success":
                        raise ValueError(
                            f"Pipeline {req.pipeline_id} has unfinished or failed jobs — "
                            "message is only generated when every stage completed successfully"
                        )
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"Could not verify pipeline jobs: {exc}") from exc

        jira_key = req.jira_key or extract_jira_key_from_branch(req.source_branch)
        if not jira_key:
            await self._deploy_repo.update_fields(
                request_id,
                status=DeployRequestStatus.NEEDS_JIRA,
                error_message="Assign a Jira key before generating the message",
            )
            raise ValueError("Jira key is required — assign it on the dashboard first")

        # Resolve tag version before enrich (pipeline ref is the source of truth)
        resolved_version = req.version
        if req.pipeline_id and hasattr(self._integrations.gitlab, "get_pipeline"):
            try:
                pipe = await self._integrations.gitlab.get_pipeline(int(req.pipeline_id))
                resolved_version = (
                    normalize_version_tag(pipe.get("ref"))
                    or extract_version_from_jobs([], pipe.get("ref"))
                    or resolved_version
                )
            except Exception:
                pass

        graph = build_enrich_graph(
            self._integrations,
            self._run_repo,
            self._deploy_repo,
            self._hitl_repo,
            force_auto_send=auto_from_pipeline and is_automatic_send_enabled(),
        )
        await graph.ainvoke(
            {
                "messages": [],
                "request_id": req.id,
                "run_id": req.run_id,
                "source_branch": req.source_branch or "",
                "target_branch": req.target_branch or self._stage_branch(),
                "mr_iid": req.mr_iid,
                "mr_url": req.mr_url,
                "pipeline_id": req.pipeline_id,
                "pipeline_url": req.pipeline_url,
                "jira_key": jira_key,
                "version": resolved_version,
            },
            config=trace_config(
                run_id=req.run_id,
                agent_name="deploy_request",
                workflow_type="deploy_request",
            ),
        )

        updated = await self._deploy_repo.get(req.id)
        assert updated is not None
        if updated.status == DeployRequestStatus.WAITING_APPROVAL:
            await self._run_repo.update_run(
                req.run_id,
                status=RunStatus.WAITING_HITL,
                output_payload={
                    "deploy_request_id": updated.id,
                    "hitl_checkpoint_id": updated.hitl_checkpoint_id,
                    "status": updated.status.value,
                },
            )
        elif updated.status == DeployRequestStatus.DRAFT:
            await self._run_repo.update_run(
                req.run_id,
                status=RunStatus.RUNNING,
                output_payload={
                    "deploy_request_id": updated.id,
                    "status": updated.status.value,
                },
            )
        elif updated.status == DeployRequestStatus.PUBLISHED:
            await self._run_repo.update_run(
                req.run_id,
                status=RunStatus.COMPLETED,
                output_payload={
                    "deploy_request_id": updated.id,
                    "status": updated.status.value,
                    "published_by": "auto",
                },
            )
        elif updated.status == DeployRequestStatus.FAILED:
            await self._run_repo.update_run(
                req.run_id,
                status=RunStatus.FAILED,
                error_message=updated.error_message,
            )
        return updated

    async def handle_pipeline_success(
        self,
        *,
        pipeline_id: int,
        pipeline_url: str | None,
        ref: str | None,
        variables: dict[str, str] | None = None,
        version: str | None = None,
        sha: str | None = None,
    ) -> DeployRequest | None:
        """Webhook / legacy entry: register successful Stage pipeline."""
        env = (variables or {}).get("ENV") or (variables or {}).get("env")
        stage = self._stage_branch()
        is_stg_tag = is_stg_version_tag(ref)
        if env and env.lower() not in ("stg", "stage", "staging") and not is_stg_tag:
            return None
        if (
            ref
            and ref != stage
            and not is_stg_tag
            and not (env and env.lower() in ("stg", "stage", "staging"))
        ):
            return None

        existing = await self._deploy_repo.get_by_pipeline_id(pipeline_id)
        if existing and existing.status in (
            DeployRequestStatus.WAITING_APPROVAL,
            DeployRequestStatus.PUBLISHED,
            DeployRequestStatus.DRAFT,
            DeployRequestStatus.PIPELINE_READY,
        ):
            return existing

        return await self.register_stage_pipeline(
            pipeline_id=pipeline_id,
            pipeline_url=pipeline_url,
            ref=ref or stage,
            sha=sha,
            version=version or normalize_version_tag(ref),
        )

    async def assign_jira(self, request_id: str, jira_key: str) -> DeployRequest:
        req = await self._deploy_repo.get(request_id)
        if not req:
            raise ValueError("Deploy request not found")
        if req.status == DeployRequestStatus.PUBLISHED:
            raise ValueError("Cannot assign Jira on a published request")

        key = jira_key.strip().upper()
        jira_title = None
        priority = req.priority
        try:
            issue = await self._integrations.jira.get_issue(key)
            jira_title = issue.get("summary")
            if not priority:
                priority = jira_priority_to_pn(issue.get("priority"))
        except Exception:
            pass

        await self._deploy_repo.update_fields(
            request_id,
            jira_key=key,
            jira_title=jira_title,
            jira_url=_jira_browse_url(key),
            priority=priority,
            error_message=None,
            status=(
                DeployRequestStatus.PIPELINE_READY
                if req.status == DeployRequestStatus.NEEDS_JIRA
                else req.status
            ),
        )

        # After assign from needs_jira, generate (and auto-send if configured)
        if req.status == DeployRequestStatus.NEEDS_JIRA:
            return await self.generate_message(
                request_id,
                auto_from_pipeline=is_automatic_send_enabled(),
            )

        updated = await self._deploy_repo.get(request_id)
        assert updated is not None
        if updated.status in (
            DeployRequestStatus.DRAFT,
            DeployRequestStatus.WAITING_APPROVAL,
        ):
            msg = build_deploy_message(updated)
            updated = await self._deploy_repo.update_fields(request_id, message_body=msg)
        assert updated is not None
        return updated

    async def update_draft(
        self,
        request_id: str,
        *,
        priority: str | None = None,
        publish_at: str | None = None,
        message_body: str | None = None,
        version: str | None = None,
        jira_key: str | None = None,
    ) -> DeployRequest:
        req = await self._deploy_repo.get(request_id)
        if not req:
            raise ValueError("Deploy request not found")
        if req.status == DeployRequestStatus.PUBLISHED:
            raise ValueError("Published requests cannot be edited")

        fields: dict[str, Any] = {}
        if priority is not None:
            fields["priority"] = priority
        if publish_at is not None:
            fields["publish_at"] = publish_at
        if version is not None:
            fields["version"] = version
        if jira_key is not None:
            key = jira_key.strip().upper()
            fields["jira_key"] = key
            fields["jira_url"] = _jira_browse_url(key)
            try:
                issue = await self._integrations.jira.get_issue(key)
                fields["jira_title"] = issue.get("summary")
                if priority is None and not req.priority:
                    fields["priority"] = jira_priority_to_pn(issue.get("priority"))
            except Exception:
                pass

        structured_updated = bool(fields)
        if fields:
            req = await self._deploy_repo.update_fields(request_id, **fields)
            assert req is not None

        # Rebuild from Jira/tag fields when structured data changed (keeps Date&Times in sync).
        # Pure message textarea edits (no publish_at/jira/…) keep the body as typed.
        if message_body is not None and not structured_updated:
            req = await self._deploy_repo.update_fields(request_id, message_body=message_body)
        else:
            assert req is not None
            msg = build_deploy_message(req)
            req = await self._deploy_repo.update_fields(request_id, message_body=msg)
        assert req is not None
        return req

    async def publish_after_approval(self, run_id: str, resolved_by: str) -> DeployRequest:
        req = await self._deploy_repo.get_by_run_id(run_id)
        if not req:
            raise ValueError(f"No deploy request for run {run_id}")
        if not req.priority:
            raise ValueError("Priority must be set on the dashboard before publish")
        if not req.publish_at:
            raise ValueError("Date&Times (publish_at) must be set before publish")

        message = build_deploy_message(req)
        try:
            response = await post_deploy_webhook(message)
            updated = await self._deploy_repo.update_fields(
                req.id,
                status=DeployRequestStatus.PUBLISHED,
                message_body=message,
                mattermost_response=str(response),
                error_message=None,
            )
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_payload={
                    "deploy_request_id": req.id,
                    "status": DeployRequestStatus.PUBLISHED.value,
                    "published_by": resolved_by,
                    "mattermost": response,
                },
            )
            await self._run_repo.log_event_by_type(
                run_id,
                AgentName.DEPLOY,
                "published",
                f"Deploy Request published by {resolved_by}",
            )
            assert updated is not None
            return updated
        except Exception as exc:
            await self._deploy_repo.update_fields(
                req.id,
                status=DeployRequestStatus.FAILED,
                error_message=str(exc),
            )
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def reject(self, run_id: str, resolved_by: str) -> None:
        req = await self._deploy_repo.get_by_run_id(run_id)
        if req and req.status != DeployRequestStatus.PUBLISHED:
            await self._deploy_repo.update_fields(
                req.id,
                status=DeployRequestStatus.FAILED,
                error_message=f"Rejected by {resolved_by}",
            )
        await self._run_repo.update_run(run_id, status=RunStatus.CANCELLED)

    async def send_to_mattermost(
        self,
        request_id: str,
        *,
        resolved_by: str = "tech-lead@dashboard",
        priority: str | None = None,
        publish_at: str | None = None,
        message_body: str | None = None,
        version: str | None = None,
        jira_key: str | None = None,
    ) -> DeployRequest:
        """Save draft fields (if provided) and post to Mattermost webhook."""
        req = await self.update_draft(
            request_id,
            priority=priority,
            publish_at=publish_at,
            message_body=message_body,
            version=version,
            jira_key=jira_key,
        )
        if not req.priority:
            raise ValueError("Priority must be set before Send to Mattermost")
        if not req.publish_at:
            raise ValueError("Date&Times (publish_at) must be set before Send to Mattermost")

        message = message_body if message_body is not None else build_deploy_message(req)
        try:
            response = await post_deploy_webhook(message)
            updated = await self._deploy_repo.update_fields(
                req.id,
                status=DeployRequestStatus.PUBLISHED,
                message_body=message,
                mattermost_response=str(response),
                error_message=None,
            )
            await self._run_repo.update_run(
                req.run_id,
                status=RunStatus.COMPLETED,
                output_payload={
                    "deploy_request_id": req.id,
                    "status": DeployRequestStatus.PUBLISHED.value,
                    "published_by": resolved_by,
                    "mattermost": response,
                },
            )
            if req.hitl_checkpoint_id:
                try:
                    await self._hitl_repo.resolve_checkpoint(
                        req.hitl_checkpoint_id,
                        action=HITLAction.APPROVE,
                        resolved_by=resolved_by,
                    )
                except Exception:
                    pass
            await self._run_repo.log_event_by_type(
                req.run_id,
                AgentName.DEPLOY,
                "published",
                f"Deploy Request sent to Mattermost by {resolved_by}",
            )
            assert updated is not None
            return updated
        except Exception as exc:
            await self._deploy_repo.update_fields(
                req.id,
                status=DeployRequestStatus.FAILED,
                error_message=str(exc),
            )
            await self._run_repo.update_run(
                req.run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def trigger_from_stage_mr(self, mr_iid: int) -> dict[str, Any]:
        """
        Manual Stage-MR button:
        - not merged → remind to merge
        - merged → find successful Stage pipeline and register it (no auto trigger)
        """
        stage = self._stage_branch()
        gitlab = self._integrations.gitlab
        mr = await gitlab.get_merge_request(mr_iid)
        target = mr.get("target_branch") or ""
        state = (mr.get("state") or "").lower()
        source = mr.get("source_branch") or ""
        web_url = mr.get("web_url")

        if target != stage:
            return {
                "ok": False,
                "action": "wrong_target",
                "message": (
                    f"MR !{mr_iid} targets {target!r}, not Stage ({stage}). "
                    "Only Stage MRs can prepare Deploy Request."
                ),
                "mr": mr,
            }

        if state != "merged":
            return {
                "ok": False,
                "action": "needs_merge",
                "message": (
                    f"MR !{mr_iid} is not merged yet (state={state}). "
                    "Please merge it into Stage in GitLab, then run bump-version "
                    "with ENV=stg on Stage (or wait for a successful Stage pipeline)."
                ),
                "mr": mr,
            }

        # Prefer pipeline already linked to this MR
        existing = await self._deploy_repo.get_by_mr_iid(mr_iid)
        if existing and existing.status != DeployRequestStatus.FAILED:
            return {
                "ok": True,
                "action": "existing",
                "message": (
                    f"Deploy Request already exists for MR !{mr_iid} "
                    f"(status={existing.status.value})"
                ),
                "deploy_request_id": existing.id,
                "status": existing.status.value,
                "mr": mr,
            }

        try:
            try:
                pipes = await gitlab.list_pipelines(
                    status="success", limit=30, scope="tags"
                )
            except TypeError:
                pipes = await gitlab.list_pipelines(status="success", limit=40)
            pipes = [p for p in pipes if is_stg_version_tag(p.get("ref"))]
        except Exception as exc:
            return {
                "ok": False,
                "action": "needs_pipeline",
                "message": f"Could not list Stage tag pipelines: {exc}",
                "mr": mr,
            }

        if not pipes:
            return {
                "ok": False,
                "action": "needs_pipeline",
                "message": (
                    f"MR !{mr_iid} is merged, but no successful Stage tag pipeline "
                    "(e.g. v2.307.0-stg) was found. Finish bump-version / tag pipeline, "
                    "then Prepare again (or wait for the 30s poller)."
                ),
                "mr": mr,
            }

        sha = mr.get("merge_commit_sha") or mr.get("sha")
        chosen = None
        for pipe in pipes:
            if sha and pipe.get("sha") == sha:
                chosen = pipe
                break
        if not chosen:
            chosen = pipes[0]

        req = await self.register_stage_pipeline(
            pipeline_id=int(chosen["id"]),
            pipeline_url=chosen.get("web_url"),
            ref=chosen.get("ref") or stage,
            sha=chosen.get("sha") or sha,
            mr_iid=mr_iid,
            mr_url=web_url,
            source_branch=source,
            force=bool(existing and existing.status == DeployRequestStatus.FAILED),
        )
        return {
            "ok": True,
            "action": "registered",
            "message": (
                f"Registered Stage pipeline {req.pipeline_id} for MR !{mr_iid} "
                f"(status={req.status.value}). "
                + (
                    "Message auto-sent."
                    if req.status == DeployRequestStatus.PUBLISHED
                    else "Open it and click Generate Message."
                )
            ),
            "deploy_request_id": req.id,
            "status": req.status.value,
            "mr": mr,
        }

    async def list_stage_pipelines_for_dashboard(self, limit: int = 30) -> list[dict[str, Any]]:
        """Deploy pipelines (Stage tags, stage branch, main) with branch/Jira preview."""
        cfg = get_deploy_branch_settings()
        stage = cfg.stage_target_branch
        production = cfg.production_target_branch
        gitlab = self._integrations.gitlab
        limit = max(1, min(limit, 100))
        try:
            pipes = await list_deploy_pipelines(
                gitlab,
                limit,
                stage_branch=stage,
                production_branch=production,
                status=None,
            )
        except Exception as exc:
            raise ValueError(f"Could not list deploy pipelines: {exc}") from exc

        out: list[dict[str, Any]] = []
        for pipe in pipes[:limit]:
            pid = pipe.get("id")
            if pid is None:
                continue
            pid_i = int(pid)
            ref = pipe.get("ref") or ""
            sha = pipe.get("sha")
            existing = await self._deploy_repo.get_by_pipeline_id(pid_i)
            mr_target = deploy_target_branch_for_ref(
                ref, stage_branch=stage, production_branch=production
            )

            mr = await find_related_merged_mr(gitlab, target_branch=mr_target, sha=sha)
            mr_ctx = context_from_mr(mr)
            jobs_ok = False
            if (pipe.get("status") or "").lower() == "success":
                jobs_ok, _, _ = await pipeline_fully_succeeded(gitlab, pid_i)

            out.append(
                {
                    "pipeline_id": pid_i,
                    "tag": ref,
                    "version": normalize_version_tag(ref),
                    "status": pipe.get("status") or "unknown",
                    "sha": sha,
                    "web_url": pipe.get("web_url"),
                    "created_at": pipe.get("created_at"),
                    "source_branch": mr_ctx.get("source_branch"),
                    "jira_key": mr_ctx.get("jira_key"),
                    "mr_iid": mr_ctx.get("mr_iid"),
                    "mr_url": mr_ctx.get("mr_url"),
                    "deploy_request_id": existing.id if existing else None,
                    "deploy_status": existing.status.value if existing else None,
                    "jobs_complete": jobs_ok,
                    "selectable": jobs_ok
                    and existing.status != DeployRequestStatus.PUBLISHED
                    if existing
                    else jobs_ok,
                }
            )
        return out

    async def open_stage_pipeline(self, pipeline_id: int) -> DeployRequest:
        """Register or return Deploy Request for a successful deploy pipeline."""
        gitlab = self._integrations.gitlab
        existing = await self._deploy_repo.get_by_pipeline_id(pipeline_id)
        if existing:
            return existing

        if not hasattr(gitlab, "get_pipeline"):
            raise ValueError("GitLab client does not support get_pipeline")

        cfg = get_deploy_branch_settings()
        stage = cfg.stage_target_branch
        production = cfg.production_target_branch

        try:
            pipe = await gitlab.get_pipeline(pipeline_id)
        except Exception as exc:
            raise ValueError(f"Pipeline {pipeline_id} not found: {exc}") from exc

        ref = pipe.get("ref")
        if not is_deploy_pipeline_ref(
            ref, stage_branch=stage, production_branch=production
        ) and not normalize_version_tag(ref):
            raise ValueError(
                f"Pipeline {pipeline_id} ref {ref!r} is not allowed "
                f"(use Stage tag, {stage!r}, or {production!r})"
            )
        if (pipe.get("status") or "").lower() != "success":
            raise ValueError(
                f"Pipeline {pipeline_id} status is {pipe.get('status')!r}; "
                "only successful pipelines can prepare a Deploy Request"
            )

        ok, jobs, detail = await pipeline_fully_succeeded(gitlab, pipeline_id)
        if not ok:
            raise ValueError(
                f"Pipeline {pipeline_id} has unfinished or failed jobs — "
                "wait until every stage completes successfully"
            )

        merged = detail or pipe
        return await self.register_stage_pipeline(
            pipeline_id=pipeline_id,
            pipeline_url=merged.get("web_url") or pipe.get("web_url"),
            ref=ref,
            sha=merged.get("sha") or pipe.get("sha"),
            jobs=jobs,
        )

    async def list_open_mrs_by_environment(self, limit: int = 30) -> dict[str, Any]:
        """Open MRs grouped by Dev / Stage / Production target branches."""
        cfg = get_deploy_branch_settings()
        branches = {
            "dev": cfg.dev_target_branch,
            "stage": cfg.stage_target_branch,
            "production": cfg.production_target_branch,
        }
        gitlab = self._integrations.gitlab
        result: dict[str, Any] = {
            "branches": branches,
            "dev": [],
            "stage": [],
            "production": [],
        }
        for env, target in branches.items():
            try:
                try:
                    mrs = await gitlab.list_merge_requests(
                        state="opened",
                        limit=limit,
                        target_branch=target,
                    )
                except TypeError:
                    mrs = await gitlab.list_merge_requests(state="opened", limit=limit * 3)
                    mrs = [m for m in mrs if m.get("target_branch") == target][:limit]
            except Exception as exc:
                result[env] = []
                result.setdefault("errors", []).append(f"{env}: {exc}")
                continue

            enriched = []
            for mr in mrs:
                iid = mr.get("iid")
                existing = await self._deploy_repo.get_by_mr_iid(int(iid)) if iid else None
                enriched.append(
                    {
                        **mr,
                        "jira_key": extract_jira_key_from_branch(mr.get("source_branch")),
                        "deploy_request_id": existing.id if existing else None,
                        "deploy_status": existing.status.value if existing else None,
                        "can_prepare": env == "stage",
                    }
                )
            result[env] = enriched
        return result
