import asyncio
import re

from core.config import get_settings
from shared.agent_executors.review_executor import build_review_prompt
from shared.cursor_cli.response_parser import is_incomplete_review_response
from shared.cursor_cli.context_builder import build_review_context
from shared.cursor_cli.prompt_builder import build_review_prompt as build_cli_review_prompt
from shared.cursor_cli.review_workspace import review_workspace_enabled
from shared.integrations.registry import get_integrations
from shared.utils.token_count import count_text_tokens
from shared.models.domain import (
    AgentName,
    CodeReviewResult,
    HITLAction,
    HITLCheckpoint,
    MergeRequestInfo,
    RunStatus,
    WorkflowType,
)
from shared.persistence.repository import AgentRunRepository, HITLRepository
from shared.deploy_settings.store import get_deploy_branch_settings
from slices.feature_pipeline.agents.sentinel import run_sentinel_review
from slices.knowledge.review_package import KnowledgePackageError, build_review_knowledge_package
from shared.review.progress import ReviewProgressReporter


def _extract_task_key(title: str, source_branch: str = "") -> str:
    for text in (title, source_branch):
        match = re.search(r"([A-Z][A-Z0-9]+-\d+)", text or "", re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def _mr_has_conflicts(mr_data: dict) -> bool:
    if mr_data.get("has_conflicts"):
        return True
    if mr_data.get("merge_status") == "cannot_be_merged":
        return True
    if mr_data.get("detailed_merge_status") in ("conflict", "not_mergeable"):
        return True
    return False


def _format_review_note(review: CodeReviewResult, *, run_id: str) -> str:
    status = "Approved" if review.approved else "Changes Requested"
    lines = [
        "## Sentinel Code Review",
        "",
        f"**Status:** {status}",
        "",
        f"**Summary:** {review.summary or '(no summary)'}",
        "",
    ]
    if review.findings:
        lines.append("### Findings")
        for item in review.findings:
            lines.append(f"- {item}")
        lines.append("")
    if review.suggestions:
        lines.append("### Suggestions")
        for item in review.suggestions:
            lines.append(f"- {item}")
        lines.append("")
    lines.append(f"_Automated review by Sentinel (run `{run_id[:8]}`)._")
    return "\n".join(lines)


class GitLabMRService:
    def __init__(
        self,
        run_repo: AgentRunRepository | None = None,
        hitl_repo: HITLRepository | None = None,
    ):
        self._run_repo = run_repo or AgentRunRepository()
        self._hitl_repo = hitl_repo or HITLRepository()

    async def list_merge_requests(
        self,
        state: str = "opened",
        limit: int = 50,
        target_branch: str | None = None,
    ) -> list[dict]:
        integrations = get_integrations()
        try:
            return await integrations.gitlab.list_merge_requests(
                state=state,
                limit=limit,
                target_branch=target_branch,
            )
        except TypeError:
            mrs = await integrations.gitlab.list_merge_requests(state=state, limit=limit * 3)
            if target_branch:
                mrs = [m for m in mrs if m.get("target_branch") == target_branch]
            return mrs[:limit]

    async def _pending_mr_hitl_map(self) -> dict[int, str]:
        pending = await self._hitl_repo.get_pending_checkpoints()
        result: dict[int, str] = {}
        for cp in pending:
            if cp.checkpoint_name != "mr_review_approval":
                continue
            mr_iid = cp.context.get("mr_iid")
            if mr_iid is not None:
                result[int(mr_iid)] = cp.id
        return result

    async def _enrich_mr_list_item(self, mr: dict, pending_by_iid: dict[int, str]) -> dict:
        iid = mr.get("iid")
        if not iid:
            return mr
        integrations = get_integrations()
        mr_data = await integrations.gitlab.get_merge_request(int(iid))
        return {
            **mr,
            "has_conflicts": _mr_has_conflicts(mr_data),
            "merge_status": mr_data.get("merge_status"),
            "pipeline_status": mr_data.get("pipeline_status"),
            "pipeline_id": mr_data.get("pipeline_id"),
            "pipeline_url": mr_data.get("pipeline_url"),
            "jira_key": _extract_task_key(mr.get("title", ""), mr.get("source_branch", "")),
            "pending_hitl_id": pending_by_iid.get(int(iid)),
        }

    async def list_merge_requests_by_environment(self, limit: int = 40) -> dict:
        cfg = get_deploy_branch_settings()
        branches = {
            "dev": cfg.dev_target_branch,
            "stage": cfg.stage_target_branch,
            "production": cfg.production_target_branch,
        }
        pending_by_iid = await self._pending_mr_hitl_map()
        sem = asyncio.Semaphore(8)

        async def enrich_env(target: str) -> list[dict]:
            mrs = await self.list_merge_requests(
                state="opened",
                limit=limit,
                target_branch=target,
            )

            async def enrich_one(mr: dict) -> dict:
                async with sem:
                    try:
                        return await self._enrich_mr_list_item(mr, pending_by_iid)
                    except Exception:
                        return {
                            **mr,
                            "jira_key": _extract_task_key(mr.get("title", ""), mr.get("source_branch", "")),
                            "pending_hitl_id": pending_by_iid.get(int(mr.get("iid") or 0)),
                        }

            return list(await asyncio.gather(*(enrich_one(mr) for mr in mrs)))

        result: dict = {"branches": branches, "dev": [], "stage": [], "production": []}
        env_keys = ("dev", "stage", "production")
        gathered = await asyncio.gather(
            *(enrich_env(branches[key]) for key in env_keys),
            return_exceptions=True,
        )
        for key, value in zip(env_keys, gathered, strict=True):
            if isinstance(value, Exception):
                result[key] = []
                result.setdefault("errors", []).append(f"{key}: {value}")
            else:
                result[key] = value
        return result

    async def get_mr_status(self, mr_iid: int) -> dict:
        integrations = get_integrations()
        mr_data = await integrations.gitlab.get_merge_request(mr_iid)
        pending_by_iid = await self._pending_mr_hitl_map()
        return {
            "has_conflicts": _mr_has_conflicts(mr_data),
            "merge_status": mr_data.get("merge_status"),
            "pipeline_status": mr_data.get("pipeline_status"),
            "pipeline_id": mr_data.get("pipeline_id"),
            "pipeline_url": mr_data.get("pipeline_url"),
            "jira_key": _extract_task_key(
                mr_data.get("title", ""),
                mr_data.get("source_branch", ""),
            ),
            "pending_hitl_id": pending_by_iid.get(mr_iid),
        }

    async def prepare_review_context(self, mr_iid: int) -> dict:
        """Build the structured review context sent to Cursor CLI (no LLM call)."""
        integrations = get_integrations()
        mr_data = await integrations.gitlab.get_merge_request(mr_iid)
        if not mr_data.get("iid"):
            raise ValueError(f"Merge request !{mr_iid} not found")

        if _mr_has_conflicts(mr_data):
            raise ValueError(
                f"MR !{mr_iid} has merge conflicts — resolve conflicts before review "
                f"(status={mr_data.get('merge_status')})"
            )

        merge_request = MergeRequestInfo(
            iid=mr_data["iid"],
            url=mr_data["web_url"],
            title=mr_data["title"],
            source_branch=mr_data["source_branch"],
            target_branch=mr_data["target_branch"],
        )
        mr_changes = await integrations.gitlab.get_merge_request_changes(mr_iid)
        task_key = _extract_task_key(merge_request.title, merge_request.source_branch)
        development_summary = mr_data.get("description") or merge_request.title

        try:
            knowledge_package = await build_review_knowledge_package(
                task_key=task_key,
                integrations=integrations,
                mr_changes=mr_changes,
                development_summary=development_summary,
            )
        except KnowledgePackageError as exc:
            raise ValueError(str(exc)) from exc

        code_context = "\n\n".join(
            f"### {change.get('new_path') or change.get('old_path')}\n{change.get('diff', '')[:2500]}"
            for change in (mr_changes or [])[:20]
        )
        prompt = build_review_prompt(
            mr=merge_request,
            task_key=task_key,
            development_summary=development_summary,
            code_context=code_context,
            mr_changes=mr_changes,
            knowledge_package=knowledge_package,
        )
        settings = get_settings()
        review_context = build_review_context(
            mr=merge_request,
            task_key=task_key,
            development_summary=development_summary,
            code_context=code_context,
            mr_changes=mr_changes,
            knowledge_package=knowledge_package,
            language=settings.cursor_review_language,
        )
        if review_workspace_enabled():
            review_context = review_context.model_copy(update={"use_review_skill": True})
        cli_prompt = build_cli_review_prompt(
            review_context,
            output_format=settings.cursor_cli_review_output_format,
        )
        return {
            "mr_iid": mr_iid,
            "task_key": task_key,
            "merge_request_url": merge_request.url,
            "title": merge_request.title,
            "source_branch": merge_request.source_branch,
            "target_branch": merge_request.target_branch,
            "prompt_chars": len(cli_prompt),
            "prompt_tokens": count_text_tokens(cli_prompt),
            "review_prompt": cli_prompt,
            "legacy_review_prompt": prompt,
            "review_context": review_context.model_dump(),
            "review_model": settings.code_review_model,
            "review_mode": "skill-worktree" if review_workspace_enabled() else "inline",
            "sections": {
                "task_prd": bool(knowledge_package.prd and len(knowledge_package.prd) > 30),
                "code_specs": bool(
                    knowledge_package.code_specs
                    and knowledge_package.code_specs.strip() not in {"", "(none)"}
                ),
                "architecture_specs": bool(
                    knowledge_package.architecture_specs
                    and "no architecture specs" not in knowledge_package.architecture_specs.lower()
                ),
                "codebase": bool(knowledge_package.source_context),
                "review_rules": bool(
                    knowledge_package.review_rules
                    and knowledge_package.review_rules.strip() not in {"", "(none)"}
                ),
            },
        }

    async def review_merge_request(
        self,
        mr_iid: int,
        reviewed_by: str = "tech-lead@company.local",
        progress: ReviewProgressReporter | None = None,
    ) -> dict:
        progress = progress or ReviewProgressReporter()
        await progress.log("start", f"Sentinel review started for MR !{mr_iid}")

        integrations = get_integrations()
        await progress.log("fetch_mr", "Fetching merge request from GitLab")
        mr_data = await integrations.gitlab.get_merge_request(mr_iid)
        if not mr_data.get("iid"):
            raise ValueError(f"Merge request !{mr_iid} not found")

        if _mr_has_conflicts(mr_data):
            raise ValueError(
                f"MR !{mr_iid} has merge conflicts — resolve conflicts before review "
                f"(status={mr_data.get('merge_status')})"
            )

        merge_request = MergeRequestInfo(
            iid=mr_data["iid"],
            url=mr_data["web_url"],
            title=mr_data["title"],
            source_branch=mr_data["source_branch"],
            target_branch=mr_data["target_branch"],
        )
        await progress.log("fetch_diff", "Loading MR file changes (unified diff)")
        mr_changes = await integrations.gitlab.get_merge_request_changes(mr_iid)
        await progress.log(
            "fetch_diff",
            f"Diff loaded — {len(mr_changes or [])} changed file(s)",
            files=len(mr_changes or []),
        )
        task_key = _extract_task_key(merge_request.title, merge_request.source_branch)
        development_summary = mr_data.get("description") or merge_request.title

        await progress.log(
            "knowledge",
            f"Building knowledge package (Jira {task_key or '—'}, Chroma specs/rules)",
        )
        try:
            knowledge_package = await build_review_knowledge_package(
                task_key=task_key,
                integrations=integrations,
                mr_changes=mr_changes,
                development_summary=development_summary,
            )
        except KnowledgePackageError as exc:
            raise ValueError(str(exc)) from exc

        await progress.log("knowledge", "Knowledge package validated")
        await progress.log("run", "Creating agent run record")
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.MR_CODE_REVIEW.value,
            agent_name=AgentName.SENTINEL,
            input_payload={
                "mr_iid": mr_iid,
                "reviewed_by": reviewed_by,
                "title": merge_request.title,
                "task_key": task_key,
            },
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        try:
            await progress.log(
                "sentinel",
                "Running Sentinel agent (worktree + skill + Cursor CLI subprocess)",
            )
            output = await run_sentinel_review(
                run_id=run_id,
                merge_request=merge_request,
                mr_changes=mr_changes,
                task_key=task_key,
                development_summary=development_summary,
                integrations=integrations,
                repo=self._run_repo,
                knowledge_package=knowledge_package,
                progress=progress,
            )
            review = output.review
            if not review:
                raise RuntimeError("Review produced no result")

            # Do not post GitLab notes for infrastructure/executor failures
            summary_lower = (review.summary or "").lower()
            review_text = "\n".join(
                [review.summary or "", *(review.findings or []), *(review.suggestions or [])]
            )
            if (
                "review failed" in summary_lower
                or "cursor bridge" in summary_lower
                or "review did not run" in summary_lower
                or is_incomplete_review_response(
                    review_text,
                    {
                        "approved": review.approved,
                        "summary": review.summary,
                        "findings": review.findings,
                        "suggestions": review.suggestions,
                    },
                )
            ):
                raise RuntimeError(review.summary or "Cursor CLI did not produce a code review")

            note_body = _format_review_note(review, run_id=run_id)
            await progress.log("gitlab_note", "Posting review summary as GitLab MR comment")
            try:
                await integrations.gitlab.create_merge_request_note(mr_iid, note_body)
                note_posted = True
            except Exception as note_exc:
                note_posted = False
                await self._run_repo.log_event_by_type(
                    run_id,
                    AgentName.SENTINEL,
                    "gitlab_note_failed",
                    str(note_exc),
                )

            checkpoint_id = await self._create_review_hitl(
                run_id=run_id,
                mr_iid=mr_iid,
                merge_request=merge_request,
                review=review,
                reviewed_by=reviewed_by,
                note_posted=note_posted,
            )
            await progress.log("hitl", "HITL checkpoint created — awaiting Tech Lead approval")

            await self._run_repo.update_run(
                run_id,
                status=RunStatus.WAITING_HITL,
                output_payload={
                    "mr_iid": mr_iid,
                    "review": review.model_dump(),
                    "review_prompt": output.review_prompt,
                    "cli_stdout": output.cli_stdout,
                    "cli_stderr": output.cli_stderr,
                    "cli_command": output.cli_command,
                    "cli_returncode": output.cli_returncode,
                    "cli_backend": output.cli_backend,
                    "merge_request_url": merge_request.url,
                    "note_posted": note_posted,
                    "hitl_checkpoint_id": checkpoint_id,
                    "knowledge_package_task": task_key,
                },
            )
            await progress.log(
                "done",
                f"Review complete — {'APPROVED' if review.approved else 'CHANGES REQUESTED'}",
                approved=review.approved,
            )
            return {
                "run_id": run_id,
                "mr_iid": mr_iid,
                "status": RunStatus.WAITING_HITL.value,
                "merge_request_url": merge_request.url,
                "review": review.model_dump(),
                "review_prompt": output.review_prompt,
                "cli_stdout": output.cli_stdout,
                "cli_stderr": output.cli_stderr,
                "cli_command": output.cli_command,
                "cli_returncode": output.cli_returncode,
                "cli_backend": output.cli_backend,
                "prompt_tokens": count_text_tokens(output.review_prompt),
                "hitl_checkpoint_id": checkpoint_id,
                "note_posted": note_posted,
                "message": (
                    f"Sentinel review completed for MR !{mr_iid}. "
                    + ("Comments posted to GitLab. " if note_posted else "GitLab note failed. ")
                    + "Approve merge or request changes from Review Agent."
                ),
            }
        except Exception as exc:
            await progress.log("error", str(exc), level="error")
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def get_last_review_for_mr(self, mr_iid: int) -> dict | None:
        """Return the most recent Sentinel review output for an MR, if any."""
        runs = await self._run_repo.list_runs(
            workflow_type=WorkflowType.MR_CODE_REVIEW.value,
            limit=100,
        )
        for run in runs:
            inp = run.get("input_payload") or {}
            if inp.get("mr_iid") != mr_iid:
                continue
            out = run.get("output_payload") or {}
            review = out.get("review")
            if not review:
                continue
            prompt = out.get("review_prompt") or ""
            return {
                "run_id": run["id"],
                "mr_iid": mr_iid,
                "status": run.get("status", ""),
                "merge_request_url": out.get("merge_request_url") or "",
                "review": review,
                "review_prompt": prompt,
                "cli_stdout": out.get("cli_stdout") or "",
                "cli_stderr": out.get("cli_stderr") or "",
                "cli_command": out.get("cli_command") or [],
                "cli_returncode": out.get("cli_returncode"),
                "cli_backend": out.get("cli_backend"),
                "prompt_tokens": count_text_tokens(prompt) if prompt else 0,
                "note_posted": out.get("note_posted"),
                "created_at": run.get("created_at", ""),
                "message": f"Last review from run {run['id'][:8]}…",
            }
        return None

    async def merge_merge_request(
        self,
        mr_iid: int,
        merged_by: str = "tech-lead@company.local",
    ) -> dict:
        integrations = get_integrations()
        mr_data = await integrations.gitlab.get_merge_request(mr_iid)
        if mr_data.get("state") != "opened":
            raise ValueError(f"MR !{mr_iid} is not open (state={mr_data.get('state')})")

        if _mr_has_conflicts(mr_data):
            raise ValueError(f"MR !{mr_iid} has merge conflicts — cannot merge")

        pipe_status = (mr_data.get("pipeline_status") or "").lower()
        if not pipe_status:
            pipeline = await integrations.gitlab.get_merge_request_pipeline_status(mr_iid)
            pipe_status = (pipeline.get("status") or "").lower()
        if pipe_status and pipe_status not in ("success", "manual"):
            raise ValueError(
                f"MR !{mr_iid} pipeline status is '{pipe_status}' — build must succeed before merge"
            )
        if not pipe_status:
            raise ValueError(
                f"MR !{mr_iid} has no pipeline — wait for CI build or trigger pipeline before merge"
            )

        title = mr_data.get("title") or f"MR !{mr_iid}"
        result = await integrations.gitlab.accept_merge_request(
            mr_iid,
            merge_commit_message=f"Merge: {title} (by {merged_by})",
        )
        return {
            "mr_iid": mr_iid,
            "state": result.get("state"),
            "merge_commit_sha": result.get("merge_commit_sha"),
            "web_url": result.get("web_url") or mr_data.get("web_url"),
            "message": f"MR !{mr_iid} merged successfully",
        }

    async def merge_after_hitl(
        self,
        *,
        run_id: str,
        mr_iid: int,
        merged_by: str,
    ) -> dict:
        return await self.merge_merge_request(mr_iid, merged_by=merged_by)

    async def _create_review_hitl(
        self,
        *,
        run_id: str,
        mr_iid: int,
        merge_request: MergeRequestInfo,
        review: CodeReviewResult,
        reviewed_by: str,
        note_posted: bool,
    ) -> str:
        for cp in await self._hitl_repo.get_pending_checkpoints():
            if cp.checkpoint_name == "mr_review_approval" and cp.context.get("mr_iid") == mr_iid:
                await self._hitl_repo.resolve_checkpoint(
                    cp.id,
                    HITLAction.REQUEST_CHANGES,
                    reviewed_by,
                )

        status_label = "Approved" if review.approved else "Changes Requested"
        checkpoint = HITLCheckpoint(
            run_id=run_id,
            checkpoint_name="mr_review_approval",
            description=(
                f"Sentinel review for MR !{mr_iid}: {status_label}. "
                "Approve to merge (if pipeline green), or request changes for developer re-review."
            ),
            context={
                "mr_iid": mr_iid,
                "merge_request_url": merge_request.url,
                "title": merge_request.title,
                "approved": review.approved,
                "summary": review.summary,
                "findings": review.findings,
                "note_posted": note_posted,
            },
        )
        saved = await self._hitl_repo.create_checkpoint(checkpoint)
        return saved.id
