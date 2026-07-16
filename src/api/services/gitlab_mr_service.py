import re

from shared.integrations.registry import get_integrations
from shared.models.domain import AgentName, MergeRequestInfo, RunStatus, WorkflowType
from shared.persistence.repository import AgentRunRepository
from slices.feature_pipeline.agents.sentinel import run_sentinel_review


def _extract_task_key(title: str) -> str:
    match = re.search(r"\[([A-Z][A-Z0-9]+-\d+)\]", title, re.IGNORECASE)
    return match.group(1).upper() if match else ""


class GitLabMRService:
    def __init__(self, run_repo: AgentRunRepository | None = None):
        self._run_repo = run_repo or AgentRunRepository()

    async def list_merge_requests(
        self,
        state: str = "opened",
        limit: int = 50,
    ) -> list[dict]:
        integrations = get_integrations()
        return await integrations.gitlab.list_merge_requests(state=state, limit=limit)

    async def review_merge_request(
        self,
        mr_iid: int,
        reviewed_by: str = "tech-lead@company.local",
    ) -> dict:
        integrations = get_integrations()
        mr_data = await integrations.gitlab.get_merge_request(mr_iid)
        if not mr_data.get("iid"):
            raise ValueError(f"Merge request !{mr_iid} not found")

        merge_request = MergeRequestInfo(
            iid=mr_data["iid"],
            url=mr_data["web_url"],
            title=mr_data["title"],
            source_branch=mr_data["source_branch"],
            target_branch=mr_data["target_branch"],
        )
        mr_changes = await integrations.gitlab.get_merge_request_changes(mr_iid)
        task_key = _extract_task_key(merge_request.title)
        development_summary = mr_data.get("description") or merge_request.title

        run_id = await self._run_repo.create_run(
            workflow_type=WorkflowType.MR_CODE_REVIEW.value,
            agent_name=AgentName.SENTINEL,
            input_payload={
                "mr_iid": mr_iid,
                "reviewed_by": reviewed_by,
                "title": merge_request.title,
            },
        )
        await self._run_repo.update_run(run_id, status=RunStatus.RUNNING)

        try:
            output = await run_sentinel_review(
                run_id=run_id,
                merge_request=merge_request,
                mr_changes=mr_changes,
                task_key=task_key,
                development_summary=development_summary,
                integrations=integrations,
                repo=self._run_repo,
            )
            review = output.review
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.COMPLETED,
                output_payload={
                    "mr_iid": mr_iid,
                    "review": review.model_dump() if review else None,
                    "merge_request_url": merge_request.url,
                },
            )
            return {
                "run_id": run_id,
                "mr_iid": mr_iid,
                "status": RunStatus.COMPLETED.value,
                "merge_request_url": merge_request.url,
                "review": review.model_dump() if review else {},
                "message": f"Sentinel review completed for MR !{mr_iid}",
            }
        except Exception as exc:
            await self._run_repo.update_run(
                run_id,
                status=RunStatus.FAILED,
                error_message=str(exc),
            )
            raise
