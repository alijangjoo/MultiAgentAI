"""Feature Development Orchestrator - coordinates Atlas, Forge, Sentinel, Scribe with HITL."""

from typing import Any

from shared.deploy_settings.store import resolve_source_branch, resolve_target_branch
from shared.integrations.factory import IntegrationContainer
from shared.integrations.registry import get_integrations
from shared.models.domain import (
    AgentName,
    HITLCheckpoint,
    RunStatus,
    SubTask,
    WorkflowType,
)
from shared.persistence.repository import AgentRunRepository, HITLRepository
from slices.feature_pipeline.agents.atlas import run_atlas
from slices.feature_pipeline.agents.develop_workflow import run_develop_workflow
from slices.feature_pipeline.agents.forge import run_forge
from slices.feature_pipeline.agents.scribe import run_scribe
from slices.feature_pipeline.agents.sentinel import run_sentinel
from slices.feature_pipeline.models.state import AtlasOutput, FeaturePipelineInput, FeaturePipelineState, ForgeOutput


class FeaturePipelineOrchestrator:
    def __init__(
        self,
        integrations: IntegrationContainer | None = None,
        run_repo: AgentRunRepository | None = None,
        hitl_repo: HITLRepository | None = None,
    ):
        self._integrations = integrations or get_integrations()
        self._run_repo = run_repo or AgentRunRepository()
        self._hitl_repo = hitl_repo or HITLRepository()

    async def start_pipeline(self, input_data: FeaturePipelineInput) -> FeaturePipelineState:
        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.FEATURE_DEVELOPMENT.value,
            agent_name=AgentName.ORCHESTRATOR,
            input_payload=input_data.model_dump(),
        )

        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.ORCHESTRATOR,
            "pipeline_started",
            f"Feature pipeline started for {input_data.task_key}",
        )

        state = FeaturePipelineState(run_id=run_id, task_key=input_data.task_key)

        try:
            atlas_output = await run_atlas(
                run_id=run_id,
                task_key=input_data.task_key,
                integrations=self._integrations,
                repo=self._run_repo,
            )
            state.atlas_output = atlas_output
            state.status = "atlas_completed"

            await self._run_repo.log_event_by_type(
                run_id,
                AgentName.ORCHESTRATOR,
                "atlas_completed",
                f"Created {len(atlas_output.subtasks)} subtasks and branch {atlas_output.branch.name if atlas_output.branch else 'N/A'}",
            )

            if not atlas_output.subtasks or not atlas_output.branch:
                raise RuntimeError("Atlas failed to create subtasks or branch")

            subtask_idx = min(input_data.subtask_index, len(atlas_output.subtasks) - 1)
            subtask = atlas_output.subtasks[subtask_idx]

            forge_output = await run_forge(
                run_id=run_id,
                task_key=input_data.task_key,
                branch_name=atlas_output.branch.name,
                subtask=subtask,
                prd_content=atlas_output.prd_content,
                integrations=self._integrations,
                repo=self._run_repo,
            )
            state.forge_output = forge_output
            state.status = "forge_completed"

            sentinel_output = await run_sentinel(
                run_id=run_id,
                task_key=input_data.task_key,
                branch_name=atlas_output.branch.name,
                task_summary=atlas_output.issue.get("summary", input_data.task_key),
                development_summary=forge_output.development_summary,
                integrations=self._integrations,
                repo=self._run_repo,
            )
            state.sentinel_output = sentinel_output
            state.status = "waiting_hitl"

            checkpoint = await self._create_merge_hitl_checkpoint(
                run_id=run_id,
                input_data=input_data,
                state=state,
            )
            state.hitl_checkpoint_id = checkpoint.id

            await self._run_repo.update_run(
                run_id,
                status=RunStatus.WAITING_HITL,
                output_payload=state.model_dump(mode="json"),
            )

            return state

        except Exception as exc:
            state.error = str(exc)
            state.status = "failed"
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def run_develop_workflow(self, input_data: FeaturePipelineInput) -> FeaturePipelineState:
        """Full LangGraph develop flow: analyze task → branch → specs → forge → MR."""
        source = resolve_source_branch(input_data.source_branch)
        target = resolve_target_branch(input_data.environment, input_data.target_branch)

        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.CODE_DEVELOPMENT.value,
            agent_name=AgentName.FORGE,
            input_payload=input_data.model_dump(),
        )

        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.ORCHESTRATOR,
            "develop_workflow_started",
            f"Develop workflow for {input_data.task_key} → MR target {target}",
        )

        state = FeaturePipelineState(run_id=run_id, task_key=input_data.task_key)

        try:
            result = await run_develop_workflow(
                run_id=run_id,
                task_key=input_data.task_key,
                environment=input_data.environment,
                source_branch=source,
                target_branch=target,
                short_description=input_data.short_description or "",
                branch_name=input_data.branch_name,
                integrations=self._integrations,
                repo=self._run_repo,
                create_mr=input_data.create_mr,
            )

            branch_name = result["branch_name"]
            mr = result.get("merge_request")

            forge_output = ForgeOutput(
                task_key=input_data.task_key,
                branch_name=branch_name,
                subtask_key=None,
                files_changed=result.get("files_changed", []),
                commit_message=f"feat({input_data.task_key}): development",
                development_summary=result.get("development_summary", ""),
                merge_request_url=mr.url if mr else None,
                merge_request_iid=mr.iid if mr else None,
                target_branch=target,
            )

            state.forge_output = forge_output
            state.status = "completed"

            await self._run_repo.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_payload=state.model_dump(mode="json"),
            )

            await self._run_repo.log_event_by_type(
                run_id,
                AgentName.ORCHESTRATOR,
                "develop_workflow_completed",
                f"Branch {branch_name}, MR: {mr.url if mr else 'N/A'}",
            )

            return state

        except Exception as exc:
            state.error = str(exc)
            state.status = "failed"
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def run_forge_only(self, input_data: FeaturePipelineInput) -> FeaturePipelineState:
        """Run full develop workflow (branch, specs, forge, MR) from dashboard."""
        if input_data.create_mr or not input_data.branch_name:
            return await self.run_develop_workflow(input_data)

        if not input_data.branch_name:
            raise ValueError("branch_name is required when create_mr is false")

        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.CODE_DEVELOPMENT.value,
            agent_name=AgentName.FORGE,
            input_payload=input_data.model_dump(),
        )

        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)
        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.ORCHESTRATOR,
            "forge_started",
            f"Forge development started for {input_data.task_key} on {input_data.branch_name}",
        )

        state = FeaturePipelineState(run_id=run_id, task_key=input_data.task_key)

        try:
            issue = await self._integrations.jira.get_issue(input_data.task_key)
            prd_content = await self._integrations.jira.get_prd_attachment_content(
                input_data.task_key
            )
            prd_content = prd_content or ""

            detail = await self._integrations.jira.get_issue_detail(input_data.task_key)
            subtasks_raw = detail.get("subtasks") or []
            subtasks: list = []
            for raw in subtasks_raw:
                subtasks.append(
                    SubTask(
                        title=raw.get("summary", raw.get("title", "Subtask")),
                        description=raw.get("description", ""),
                        estimated_hours=8.0,
                        jira_key=raw.get("key"),
                    )
                )
            if not subtasks:
                subtasks = [
                    SubTask(
                        title=issue.get("summary", input_data.task_key),
                        description=issue.get("description", ""),
                        estimated_hours=8.0,
                    )
                ]

            subtask_idx = min(input_data.subtask_index, len(subtasks) - 1)
            subtask = subtasks[subtask_idx]

            forge_output = await run_forge(
                run_id=run_id,
                task_key=input_data.task_key,
                branch_name=input_data.branch_name,
                subtask=subtask,
                prd_content=prd_content,
                integrations=self._integrations,
                repo=self._run_repo,
            )
            state.forge_output = forge_output
            state.status = "completed"
            state.atlas_output = AtlasOutput(
                task_key=input_data.task_key,
                issue=issue,
                subtasks=subtasks,
                branch=None,
                prd_content=prd_content,
            )

            await self._run_repo.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_payload=state.model_dump(mode="json"),
            )

            await self._run_repo.log_event_by_type(
                run_id,
                AgentName.ORCHESTRATOR,
                "forge_completed",
                f"Forge completed on branch {input_data.branch_name}",
            )

            return state

        except Exception as exc:
            state.error = str(exc)
            state.status = "failed"
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise

    async def _create_merge_hitl_checkpoint(
        self,
        run_id: str,
        input_data: FeaturePipelineInput,
        state: FeaturePipelineState,
    ) -> HITLCheckpoint:
        mr = state.sentinel_output.merge_request if state.sentinel_output else None
        review = state.sentinel_output.review if state.sentinel_output else None

        checkpoint = HITLCheckpoint(
            run_id=run_id,
            checkpoint_name="final_merge_approval",
            description=(
                f"Review and approve merge for {input_data.task_key}. "
                f"MR: {mr.url if mr else 'N/A'}. "
                f"Review status: {'approved' if review and review.approved else 'changes requested'}."
            ),
            context={
                "task_key": input_data.task_key,
                "merge_request_url": mr.url if mr else None,
                "merge_request_iid": mr.iid if mr else None,
                "review_approved": review.approved if review else False,
                "review_summary": review.summary if review else "",
                "review_findings": review.findings if review else [],
                "tech_lead_email": input_data.tech_lead_email,
                "confluence_page_id": input_data.confluence_page_id,
            },
        )
        return await self._hitl_repo.create_checkpoint(checkpoint)

    async def complete_after_merge(
        self,
        run_id: str,
        merged_by: str,
    ) -> FeaturePipelineState:
        run = await self._run_repo.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        output = run.get("output_payload", {})
        state = FeaturePipelineState(**{**output, "run_id": run_id})

        input_data = FeaturePipelineInput(**run["input_payload"])

        scribe_output = await run_scribe(
            run_id=run_id,
            task_key=state.task_key,
            task_summary=state.atlas_output.issue.get("summary", state.task_key)
            if state.atlas_output
            else state.task_key,
            development_summary=state.forge_output.development_summary
            if state.forge_output
            else "",
            review_summary=state.sentinel_output.review.summary
            if state.sentinel_output and state.sentinel_output.review
            else "",
            confluence_page_id=input_data.confluence_page_id,
            integrations=self._integrations,
            repo=self._run_repo,
        )

        state.scribe_output = scribe_output
        state.status = "completed"

        await self._run_repo.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            output_payload=state.model_dump(mode="json"),
        )

        await self._run_repo.log_event_by_type(
            run_id,
            AgentName.ORCHESTRATOR,
            "pipeline_completed",
            f"Pipeline completed after merge by {merged_by}",
        )

        return state

    async def get_state(self, run_id: str) -> FeaturePipelineState | None:
        run = await self._run_repo.get_run(run_id)
        if not run:
            return None
        output = run.get("output_payload") or {}
        return FeaturePipelineState(
            run_id=run_id,
            task_key=run["input_payload"].get("task_key", ""),
            status=run["status"],
            **{k: v for k, v in output.items() if k not in ("run_id", "task_key", "status")},
        )
