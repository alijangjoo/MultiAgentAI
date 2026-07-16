from typing import Any

from core.config import get_settings
from shared.integrations.registry import get_integrations
from shared.utils.branch_naming import build_feature_branch_name, slugify
from shared.utils.branch_slug_ai import suggest_branch_slug
from shared.utils.gitlab_branches import normalize_branch_list


class JiraTaskService:
    def __init__(self):
        self._integrations = None

    def _container(self):
        if self._integrations is None:
            self._integrations = get_integrations()
        return self._integrations

    async def list_tasks(
        self,
        project_key: str | None = None,
        max_results: int = 50,
        status: str | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        project = project_key or settings.jira_project_key
        issues = await self._container().jira.search_issues(
            project_key=project,
            max_results=max_results,
            status=status,
        )
        return {"project_key": project, "count": len(issues), "tasks": issues}

    async def get_task_detail(self, issue_key: str) -> dict[str, Any]:
        detail = await self._container().jira.get_issue_detail(issue_key.upper())
        short_desc = slugify(detail.get("summary", ""))
        detail["suggested_short_description"] = short_desc
        detail["suggested_branch_name"] = build_feature_branch_name(
            task_key=detail["key"],
            task_summary=detail.get("summary", ""),
            short_description=short_desc,
        )
        settings = get_settings()
        detail["default_source_branch"] = settings.gitlab_feature_source_branch
        return detail

    async def suggest_branch_slug(self, issue_key: str) -> dict[str, str]:
        detail = await self._container().jira.get_issue_detail(issue_key.upper())
        return await suggest_branch_slug(
            task_key=detail["key"],
            summary=detail.get("summary", ""),
            description=detail.get("description", ""),
            prd_preview=detail.get("prd_preview"),
        )

    def preview_branch_name(
        self,
        task_key: str,
        task_summary: str,
        short_description: str,
    ) -> dict[str, str]:
        branch_name = build_feature_branch_name(
            task_key=task_key,
            task_summary=task_summary,
            short_description=short_description,
        )
        return {"branch_name": branch_name, "short_description": slugify(short_description)}

    async def create_task_branch(
        self,
        issue_key: str,
        short_description: str,
        source_branch: str | None = None,
        branch_name: str | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        issue = await self._container().jira.get_issue(issue_key.upper())
        ref = source_branch or settings.gitlab_feature_source_branch

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
            "created": result.get("created", True),
            "exists": result.get("exists", False),
            "gitlab": result,
        }

    async def list_source_branches(self, limit: int = 100) -> list[str]:
        gitlab = self._container().gitlab
        settings = get_settings()
        if hasattr(gitlab, "list_branches"):
            remote = await gitlab.list_branches(limit=limit)
            return normalize_branch_list(remote, limit=limit)
        return normalize_branch_list([settings.gitlab_feature_source_branch, settings.gitlab_default_branch])
