from typing import Any

from core.config import get_settings
from shared.integrations.registry import get_integrations
from shared.utils.branch_naming import build_feature_branch_name, slugify


class JiraBoardService:
    def __init__(self):
        self._integrations = None

    def _container(self):
        if self._integrations is None:
            self._integrations = get_integrations()
        return self._integrations

    def get_board_config(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "project_key": settings.jira_project_key,
            "default_source_branch": settings.gitlab_default_branch,
            "branch_prefix": "Feature",
            "branch_format": "Feature/{task-key}-{short-description}",
            "branch_example": "Feature/ven-100-create-api-for-contract",
        }

    async def list_tasks(
        self,
        project_key: str | None = None,
        status: str | None = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        key = project_key or settings.jira_project_key
        return await self._container().jira.search_issues(
            project_key=key,
            max_results=max_results,
            status=status,
        )

    async def get_task_detail(self, issue_key: str) -> dict[str, Any]:
        return await self._container().jira.get_issue_detail(issue_key.upper())

    def preview_branch_name(
        self,
        task_key: str,
        task_summary: str,
        short_description: str,
    ) -> str:
        return build_feature_branch_name(
            task_key=task_key,
            task_summary=task_summary,
            short_description=short_description,
        )

    async def create_branch(
        self,
        task_key: str,
        short_description: str,
        source_branch: str | None = None,
        branch_name: str | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        issue = await self._container().jira.get_issue(task_key.upper())
        ref = source_branch or settings.gitlab_default_branch

        final_branch = branch_name or build_feature_branch_name(
            task_key=issue["key"],
            task_summary=issue.get("summary", ""),
            short_description=short_description,
        )

        result = await self._container().gitlab.create_branch(
            branch_name=final_branch,
            ref=ref,
        )

        return {
            "task_key": issue["key"],
            "branch_name": final_branch,
            "source_branch": ref,
            "short_description": short_description,
            "created": result.get("created", True),
            "exists": result.get("exists", False),
            "summary": issue.get("summary", ""),
        }

    async def list_source_branches(self, limit: int = 30) -> list[str]:
        gitlab = self._container().gitlab
        settings = get_settings()
        branches: list[str] = []

        if hasattr(gitlab, "list_branches"):
            branches = await gitlab.list_branches(limit=limit)

        default = settings.gitlab_default_branch
        if default and default not in branches:
            branches.insert(0, default)

        common = ["main", "develop", "master"]
        for name in common:
            if name not in branches:
                branches.append(name)

        return branches

    @staticmethod
    def suggest_short_description(summary: str) -> str:
        return slugify(summary)
