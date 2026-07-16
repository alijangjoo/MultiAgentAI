from typing import Any

from shared.integrations.registry import get_integrations


class GitLabPipelineService:
    def __init__(self):
        self._integrations = None

    def _gitlab(self):
        if self._integrations is None:
            self._integrations = get_integrations()
        return self._integrations.gitlab

    async def list_pipelines(
        self,
        ref: str | None = None,
        status: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        gitlab = self._gitlab()
        if not hasattr(gitlab, "list_pipelines"):
            raise NotImplementedError("GitLab pipeline API not available")
        return await gitlab.list_pipelines(ref=ref, status=status, limit=limit)

    async def list_jobs(self, pipeline_id: int) -> list[dict[str, Any]]:
        gitlab = self._gitlab()
        if not hasattr(gitlab, "list_pipeline_jobs"):
            raise NotImplementedError("GitLab pipeline jobs API not available")
        return await gitlab.list_pipeline_jobs(pipeline_id)

    async def play_job(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        gitlab = self._gitlab()
        if not hasattr(gitlab, "play_job"):
            raise NotImplementedError("GitLab play job API not available")
        cleaned = [
            {"key": v["key"].strip(), "value": v["value"]}
            for v in (variables or [])
            if v.get("key", "").strip()
        ]
        return await gitlab.play_job(job_id, cleaned or None)

    async def retry_job(
        self,
        job_id: int,
        variables: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        gitlab = self._gitlab()
        if not hasattr(gitlab, "retry_job"):
            raise NotImplementedError("GitLab retry job API not available")
        cleaned = [
            {"key": v["key"].strip(), "value": v["value"]}
            for v in (variables or [])
            if v.get("key", "").strip()
        ]
        return await gitlab.retry_job(job_id, cleaned or None)
