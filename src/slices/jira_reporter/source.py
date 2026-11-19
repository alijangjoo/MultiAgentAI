"""Read the active Ven Board sprint from Jira."""

from __future__ import annotations

from typing import Any

from shared.integrations.base import run_sync

BOARD_NAME = "Ven Board"


def _status_name(fields: dict[str, Any]) -> str:
    status = fields.get("status") or {}
    return str(status.get("name") or "")


def _normalize_issue(issue: Any, sprint_id: Any) -> dict[str, Any]:
    fields = getattr(issue, "fields", None)
    raw_fields = {}
    if fields is not None:
        raw_fields = {
            "summary": getattr(fields, "summary", "") or "",
            "status": _status_name({"status": {"name": getattr(getattr(fields, "status", None), "name", "")}}),
            "issuetype": getattr(getattr(fields, "issuetype", None), "name", "") or "",
            "assignee": getattr(getattr(fields, "assignee", None), "displayName", None),
            "created": getattr(fields, "created", "") or "",
            "updated": getattr(fields, "updated", "") or "",
        }
    changelog = []
    histories = getattr(getattr(issue, "changelog", None), "histories", []) or []
    for history in histories:
        at = getattr(history, "created", "") or ""
        for item in getattr(history, "items", []) or []:
            if getattr(item, "field", "") != "status":
                continue
            changelog.append({
                "at": at,
                "from": getattr(item, "fromString", "") or "",
                "to": getattr(item, "toString", "") or "",
            })
    return {
        "key": getattr(issue, "key", ""),
        "summary": raw_fields.get("summary", ""),
        "status": raw_fields.get("status", ""),
        "issue_type": raw_fields.get("issuetype", ""),
        "assignee": raw_fields.get("assignee"),
        "created": raw_fields.get("created", ""),
        "updated": raw_fields.get("updated", ""),
        "changelog": changelog,
        "sprint_id": sprint_id,
    }


def _find_board(client: Any, project_key: str) -> Any:
    wanted = BOARD_NAME.casefold()
    found = list(client.boards(name=BOARD_NAME, maxResults=20) or [])
    matches = [board for board in found if str(getattr(board, "name", "")).casefold() == wanted]
    if not matches:
        matches = [board for board in found if wanted in str(getattr(board, "name", "")).casefold()]
    if not matches:
        found = list(client.boards(projectKeyOrID=project_key, maxResults=50) or [])
        matches = [board for board in found if wanted in str(getattr(board, "name", "")).casefold()]
    if not matches:
        raise ValueError(f"Board '{BOARD_NAME}' was not found for project {project_key}")
    return matches[0]


def _load_sync(client: Any, project_key: str) -> dict[str, Any]:
    board = _find_board(client, project_key)
    sprints = list(client.sprints(board.id, state="active", maxResults=10) or [])
    sprint_rows = []
    issues: list[dict[str, Any]] = []
    truncated = False
    for sprint in sprints:
        sprint_rows.append({
            "id": sprint.id,
            "name": getattr(sprint, "name", "") or str(sprint.id),
            "start": getattr(sprint, "startDate", None),
            "end": getattr(sprint, "endDate", None),
            "state": getattr(sprint, "state", "active"),
        })
        batch = client.search_issues(
            f"sprint = {sprint.id} ORDER BY updated DESC",
            maxResults=200,
            expand="changelog",
            fields="summary,status,issuetype,assignee,created,updated",
        )
        if len(batch) >= 200:
            truncated = True
        for issue in batch:
            issues.append(_normalize_issue(issue, sprint.id))
    return {
        "board_name": getattr(board, "name", BOARD_NAME) or BOARD_NAME,
        "sprints": sprint_rows,
        "issues": issues,
        "truncated": truncated,
    }


async def load_snapshot(jira: Any, project_key: str) -> dict[str, Any]:
    client = getattr(jira, "_client", None)
    if client is None:
        raise ValueError("Jira is mocked. Set USE_MOCK_JIRA=false to read Ven Board.")
    try:
        return await run_sync(_load_sync, client, project_key)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Jira board read failed: {exc}") from exc