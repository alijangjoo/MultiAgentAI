from typing import Any


def extract_text_from_adf(node: Any) -> str:
    """Convert Atlassian Document Format (ADF) to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")

    parts: list[str] = []
    for child in node.get("content", []):
        text = extract_text_from_adf(child)
        if text:
            parts.append(text)

    block_types = {"paragraph", "heading", "listItem", "bulletList", "orderedList", "codeBlock"}
    separator = "\n" if node_type in block_types else " "
    return separator.join(parts)


def normalize_jira_description(description: Any) -> str:
    if description is None:
        return ""
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        return extract_text_from_adf(description).strip()
    return str(description)


def format_jira_estimate(hours: float) -> str:
    whole_hours = max(1, int(hours))
    return f"{whole_hours}h"


def pick_subtask_issue_type(meta: dict[str, Any]) -> str | None:
    """Pick a sub-task issue type name from project metadata."""
    preferred = ("Sub-task", "Subtask", "Sub-Task", "sub-task")
    issue_types = meta.get("issueTypes", []) or meta.get("issuetypes", [])

    subtask_names = [it.get("name", "") for it in issue_types if it.get("subtask")]
    for candidate in preferred:
        for name in subtask_names:
            if name.lower() == candidate.lower():
                return name

    return subtask_names[0] if subtask_names else None
