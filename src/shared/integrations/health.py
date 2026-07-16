from typing import Any

from core.config import get_settings
from shared.integrations.registry import get_integrations


class IntegrationHealthService:
    def __init__(self):
        self._integrations = None

    def _container(self):
        if self._integrations is None:
            self._integrations = get_integrations()
        return self._integrations

    async def check_jira(self) -> dict[str, Any]:
        settings = get_settings()
        result = await self._container().jira.test_connection()
        result["mock"] = settings.should_mock_jira()
        return result

    async def check_gitlab(self) -> dict[str, Any]:
        settings = get_settings()
        result = await self._container().gitlab.test_connection()
        result["mock"] = settings.should_mock_gitlab()
        return result

    async def check_all(self) -> dict[str, Any]:
        jira = await self.check_jira()
        gitlab = await self.check_gitlab()
        return {
            "jira": jira,
            "gitlab": gitlab,
            "all_ok": jira.get("ok") and gitlab.get("ok"),
        }

    async def get_jira_issue(self, issue_key: str) -> dict[str, Any]:
        return await self._container().jira.get_issue(issue_key)

    async def get_gitlab_project(self) -> dict[str, Any]:
        result = await self._container().gitlab.test_connection()
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "GitLab connection failed"))
        return result.get("project", {})

    async def list_gitlab_branches(self, search: str | None = None, limit: int = 20) -> list[str]:
        gitlab = self._container().gitlab
        if hasattr(gitlab, "list_branches"):
            return await gitlab.list_branches(search=search, limit=limit)
        return []
