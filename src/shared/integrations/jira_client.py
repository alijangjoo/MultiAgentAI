from typing import Any, Literal

from shared.integrations.base import run_sync
from shared.integrations.jira_helpers import (
    format_jira_estimate,
    normalize_jira_description,
    pick_subtask_issue_type,
)
from shared.integrations.protocols import JiraClientProtocol

JiraAuthType = Literal["pat", "basic"]


class MockJiraClient(JiraClientProtocol):
    _MOCK_ISSUES: dict[str, dict[str, Any]] = {
        "VEN-100": {
            "key": "VEN-100",
            "summary": "Create API for contract management",
            "description": (
                "Implement REST API endpoints for contract CRUD operations.\n"
                "Follow CQRS pattern with separate command/query handlers.\n"
                "PRD attachment: contract-api-prd.md"
            ),
            "status": "To Do",
            "issue_type": "Story",
            "assignee": "Dev Team",
            "priority": "High",
            "labels": ["backend", "api"],
            "updated": "2026-07-01T10:00:00.000Z",
        },
        "VEN-101": {
            "key": "VEN-101",
            "summary": "Add Redis caching for contract queries",
            "description": "Implement Redis cache layer for GET contract endpoints.",
            "status": "In Progress",
            "issue_type": "Task",
            "assignee": "Dev Team",
            "priority": "Medium",
            "labels": ["backend", "redis"],
            "updated": "2026-07-02T14:30:00.000Z",
        },
        "VEN-102": {
            "key": "VEN-102",
            "summary": "Payment webhook integration",
            "description": "Integrate payment webhook handler with RabbitMQ events.",
            "status": "To Do",
            "issue_type": "Story",
            "assignee": None,
            "priority": "High",
            "labels": ["integration"],
            "updated": "2026-07-03T09:15:00.000Z",
        },
    }

    _MOCK_PRD = """# Contract API PRD

## Overview
Build contract management API for the commercial team.

## Requirements
1. POST /api/v1/contracts - Create contract
2. GET /api/v1/contracts/{id} - Get contract by ID
3. PUT /api/v1/contracts/{id} - Update contract
4. DELETE /api/v1/contracts/{id} - Soft delete contract

## Technical Constraints
- .NET 8 Web API
- CQRS with MediatR
- MySQL persistence via EF Core
- Redis caching for GET operations
- RabbitMQ events on contract changes

## Acceptance Criteria
- All endpoints return proper HTTP status codes
- Validation via FluentValidation
- Unit tests with >80% coverage
"""

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        if issue_key not in self._MOCK_ISSUES:
            return {
                "key": issue_key,
                "summary": f"Task {issue_key}",
                "description": "No description available.",
                "status": "To Do",
                "issue_type": "Task",
            }
        return self._MOCK_ISSUES[issue_key]

    async def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str,
        estimated_hours: float,
    ) -> str:
        sub_key = f"{parent_key}-{len(summary) % 10 + 1}"
        return sub_key

    async def create_story(
        self,
        summary: str,
        description: str,
        issue_type: str = "Story",
        labels: list[str] | None = None,
    ) -> str:
        next_id = len(self._MOCK_ISSUES) + 100
        key = f"VEN-{next_id}"
        self._MOCK_ISSUES[key] = {
            "key": key,
            "summary": summary,
            "description": description,
            "status": "To Do",
            "issue_type": issue_type,
            "assignee": None,
            "priority": "Medium",
            "labels": labels or ["agent-generated"],
            "updated": "2026-07-05T12:00:00.000Z",
        }
        return key

    async def transition_issue(self, issue_key: str, transition_name: str) -> None:
        pass

    async def get_prd_attachment_content(self, issue_key: str) -> str | None:
        return self._MOCK_PRD

    async def get_attachment_contents(self, issue_key: str) -> list[dict[str, Any]]:
        prd = self._MOCK_PRD
        if not prd:
            return []
        return [
            {
                "filename": "contract-api-prd.md",
                "content": prd,
                "mime_type": "text/markdown",
            }
        ]

    async def search_issues(
        self,
        project_key: str,
        max_results: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        issues = []
        for issue in self._MOCK_ISSUES.values():
            if not issue["key"].startswith(f"{project_key}-"):
                continue
            if status and issue.get("status", "").lower() != status.lower():
                continue
            issues.append(
                {
                    "key": issue["key"],
                    "summary": issue["summary"],
                    "status": issue["status"],
                    "issue_type": issue["issue_type"],
                    "assignee": issue.get("assignee"),
                    "priority": issue.get("priority"),
                    "labels": issue.get("labels", []),
                    "updated": issue.get("updated"),
                }
            )
        return issues[:max_results]

    async def get_issue_detail(self, issue_key: str) -> dict[str, Any]:
        issue = await self.get_issue(issue_key)
        prd = await self.get_prd_attachment_content(issue_key)
        return {
            **issue,
            "reporter": "Product Owner",
            "created": "2026-06-20T08:00:00.000Z",
            "updated": self._MOCK_ISSUES.get(issue_key, {}).get("updated", ""),
            "attachments": [{"filename": "contract-api-prd.md", "size": 2048}] if prd else [],
            "has_prd": bool(prd),
            "prd_preview": (prd[:500] + "...") if prd and len(prd) > 500 else prd,
            "subtasks": [],
            "jira_url": f"https://jira.company.local/browse/{issue_key}",
        }

    async def test_connection(self) -> dict[str, Any]:
        return {"ok": True, "mode": "mock", "user": "mock-user", "auth_type": "mock"}


class RealJiraClient(JiraClientProtocol):
    """
    Jira client using the official `jira` Python library.

    Auth modes:
    - pat (default): Personal Access Token via Bearer header (token_auth=...)
      Same as: JIRA(server=url, token_auth=token)
    - basic: Username + password/API token via Basic auth
      Used for Atlassian Cloud email + API token
    """

    def __init__(
        self,
        url: str,
        api_token: str,
        username: str = "",
        verify_ssl: bool = True,
        auth_type: JiraAuthType = "pat",
        subtask_issue_type: str | None = None,
        prd_field_id: str | None = None,
    ):
        from jira import JIRA

        if not url or not api_token:
            raise ValueError("JIRA_URL and JIRA_API_TOKEN are required")
        if auth_type == "basic" and not username:
            raise ValueError("JIRA_USERNAME is required when JIRA_AUTH_TYPE=basic")

        self._url = url.rstrip("/")
        self._username = username
        self._token = api_token
        self._verify_ssl = verify_ssl
        self._auth_type: JiraAuthType = auth_type
        self._subtask_issue_type = subtask_issue_type
        self._prd_field_id = prd_field_id

        if auth_type == "pat":
            self._client = JIRA(
                server=self._url,
                token_auth=api_token,
                options={"verify": verify_ssl},
            )
        else:
            self._client = JIRA(
                server=self._url,
                basic_auth=(username, api_token),
                options={"verify": verify_ssl},
            )

    def _get_issue_sync(self, issue_key: str) -> dict[str, Any]:
        issue = self._client.issue(issue_key)
        return issue.raw

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        issue = await run_sync(self._get_issue_sync, issue_key)
        fields = issue.get("fields", {})
        return {
            "key": issue.get("key", issue_key),
            "summary": fields.get("summary", ""),
            "description": normalize_jira_description(fields.get("description")),
            "status": fields.get("status", {}).get("name", ""),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "assignee": (fields.get("assignee") or {}).get("displayName"),
            "priority": (fields.get("priority") or {}).get("name"),
            "labels": fields.get("labels", []),
        }

    def _resolve_subtask_type(self, project_key: str) -> str:
        if self._subtask_issue_type:
            return self._subtask_issue_type

        meta = self._client.createmeta(
            projectKeys=project_key,
            expand="projects.issuetypes",
        )
        projects = meta.get("projects", [])
        issue_types = projects[0].get("issuetypes", []) if projects else []
        resolved = pick_subtask_issue_type({"issueTypes": issue_types})
        if not resolved:
            raise ValueError(
                f"No sub-task issue type found for project {project_key}. "
                "Set JIRA_SUBTASK_ISSUE_TYPE in .env (e.g. Sub-task)."
            )
        return resolved

    def _create_subtask_sync(
        self,
        parent_key: str,
        summary: str,
        description: str,
        estimated_hours: float,
    ) -> str:
        project_key = parent_key.split("-")[0]
        issue_type = self._resolve_subtask_type(project_key)

        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "parent": {"key": parent_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "timetracking": {"originalEstimate": format_jira_estimate(estimated_hours)},
        }

        issue = self._client.create_issue(fields=fields)
        return issue.key

    async def create_subtask(
        self,
        parent_key: str,
        summary: str,
        description: str,
        estimated_hours: float,
    ) -> str:
        return await run_sync(
            self._create_subtask_sync,
            parent_key,
            summary,
            description,
            estimated_hours,
        )

    def _create_story_sync(
        self,
        summary: str,
        description: str,
        issue_type: str,
        labels: list[str] | None,
    ) -> str:
        from core.config import get_settings

        settings = get_settings()
        fields: dict[str, Any] = {
            "project": {"key": settings.jira_project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
        }
        if labels:
            fields["labels"] = labels
        issue = self._client.create_issue(fields=fields)
        return issue.key

    async def create_story(
        self,
        summary: str,
        description: str,
        issue_type: str = "Story",
        labels: list[str] | None = None,
    ) -> str:
        return await run_sync(
            self._create_story_sync,
            summary,
            description,
            issue_type,
            labels,
        )

    def _transition_sync(self, issue_key: str, transition_name: str) -> None:
        transitions = self._client.transitions(issue_key)
        for transition in transitions:
            if transition.get("name", "").lower() == transition_name.lower():
                self._client.transition_issue(issue_key, transition["id"])
                return
        raise ValueError(f"Transition '{transition_name}' not found for {issue_key}")

    async def transition_issue(self, issue_key: str, transition_name: str) -> None:
        await run_sync(self._transition_sync, issue_key, transition_name)

    def _download_attachment_sync(self, content_url: str) -> str:
        response = self._client._session.get(content_url, verify=self._verify_ssl)
        response.raise_for_status()
        return response.text

    async def get_prd_attachment_content(self, issue_key: str) -> str | None:
        issue = await run_sync(self._get_issue_sync, issue_key)
        fields = issue.get("fields", {})

        if self._prd_field_id:
            custom_value = fields.get(self._prd_field_id)
            if custom_value:
                if isinstance(custom_value, str):
                    return custom_value
                if isinstance(custom_value, dict):
                    return normalize_jira_description(custom_value)

        attachments = fields.get("attachment", []) or []
        prd_extensions = (".md", ".txt", ".markdown", ".pdf", ".doc", ".docx")

        for attachment in attachments:
            filename = attachment.get("filename", "").lower()
            if "prd" in filename and filename.endswith(prd_extensions):
                content_url = attachment.get("content")
                if content_url:
                    return await run_sync(self._download_attachment_sync, content_url)

        for attachment in attachments:
            filename = attachment.get("filename", "").lower()
            if filename.endswith((".md", ".txt", ".markdown")):
                content_url = attachment.get("content")
                if content_url:
                    return await run_sync(self._download_attachment_sync, content_url)

        description = normalize_jira_description(fields.get("description"))
        if "prd" in description.lower():
            return description

        return None

    async def get_attachment_contents(self, issue_key: str) -> list[dict[str, Any]]:
        issue = await run_sync(self._get_issue_sync, issue_key)
        fields = issue.get("fields", {})
        attachments = fields.get("attachment", []) or []
        text_extensions = (".md", ".txt", ".markdown", ".json", ".yaml", ".yml", ".csv")
        results: list[dict[str, Any]] = []

        for attachment in attachments:
            filename = attachment.get("filename", "")
            content_url = attachment.get("content")
            if not content_url:
                continue
            lower = filename.lower()
            if not lower.endswith(text_extensions) and "prd" not in lower:
                results.append(
                    {
                        "filename": filename,
                        "content": f"[Binary or unsupported attachment: {filename}]",
                        "mime_type": attachment.get("mimeType"),
                    }
                )
                continue
            try:
                content = await run_sync(self._download_attachment_sync, content_url)
            except Exception:
                content = f"[Could not download: {filename}]"
            results.append(
                {
                    "filename": filename,
                    "content": content,
                    "mime_type": attachment.get("mimeType"),
                }
            )
        return results

    def _search_issues_sync(
        self,
        project_key: str,
        max_results: int,
        status: str | None,
    ) -> list[dict[str, Any]]:
        jql = f'project = "{project_key}" AND issuetype != Sub-task ORDER BY updated DESC'
        if status:
            jql = (
                f'project = "{project_key}" AND issuetype != Sub-task '
                f'AND status = "{status}" ORDER BY updated DESC'
            )
        results = self._client.search_issues(jql, maxResults=max_results)
        items = []
        for issue in results:
            fields = issue.raw.get("fields", {})
            items.append(
                {
                    "key": issue.key,
                    "summary": fields.get("summary", ""),
                    "status": fields.get("status", {}).get("name", ""),
                    "issue_type": fields.get("issuetype", {}).get("name", ""),
                    "assignee": (fields.get("assignee") or {}).get("displayName"),
                    "priority": (fields.get("priority") or {}).get("name"),
                    "labels": fields.get("labels", []),
                    "updated": fields.get("updated", ""),
                }
            )
        return items

    async def search_issues(
        self,
        project_key: str,
        max_results: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return await run_sync(
            self._search_issues_sync,
            project_key,
            max_results,
            status,
        )

    async def get_issue_detail(self, issue_key: str) -> dict[str, Any]:
        issue = await run_sync(self._get_issue_sync, issue_key.upper())
        fields = issue.get("fields", {})
        attachments = [
            {
                "filename": att.get("filename", ""),
                "size": att.get("size", 0),
                "created": att.get("created", ""),
            }
            for att in (fields.get("attachment") or [])
        ]
        prd = await self.get_prd_attachment_content(issue_key)
        subtasks = []
        for link in fields.get("subtasks") or []:
            subtasks.append(
                {
                    "key": link.get("key", ""),
                    "summary": link.get("fields", {}).get("summary", ""),
                    "status": link.get("fields", {}).get("status", {}).get("name", ""),
                }
            )
        return {
            "key": issue.get("key", issue_key),
            "summary": fields.get("summary", ""),
            "description": normalize_jira_description(fields.get("description")),
            "status": fields.get("status", {}).get("name", ""),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "assignee": (fields.get("assignee") or {}).get("displayName"),
            "reporter": (fields.get("reporter") or {}).get("displayName"),
            "priority": (fields.get("priority") or {}).get("name"),
            "labels": fields.get("labels", []),
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "attachments": attachments,
            "has_prd": bool(prd),
            "prd_preview": (prd[:500] + "...") if prd and len(prd) > 500 else prd,
            "subtasks": subtasks,
            "jira_url": f"{self._url}/browse/{issue.get('key', issue_key)}",
        }

    def _test_connection_sync(self) -> dict[str, Any]:
        myself = self._client.myself()
        return {
            "ok": True,
            "mode": "real",
            "url": self._url,
            "auth_type": self._auth_type,
            "user": myself.get("displayName") or myself.get("name"),
            "account_id": myself.get("accountId") or myself.get("key"),
            "email": myself.get("emailAddress"),
        }

    async def test_connection(self) -> dict[str, Any]:
        try:
            return await run_sync(self._test_connection_sync)
        except Exception as exc:
            return {
                "ok": False,
                "mode": "real",
                "url": self._url,
                "auth_type": self._auth_type,
                "error": str(exc),
            }
