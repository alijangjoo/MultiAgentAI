"""Map Jira priority names to Deploy Request Pn labels."""

from __future__ import annotations

_PRIORITY_MAP = {
    "highest": "P1",
    "critical": "P1",
    "blocker": "P1",
    "high": "P1",
    "medium": "P2",
    "normal": "P2",
    "low": "P3",
    "lowest": "P4",
    "trivial": "P4",
}


def jira_priority_to_pn(priority: str | None) -> str | None:
    if not priority:
        return None
    key = priority.strip().lower()
    if key in _PRIORITY_MAP:
        return _PRIORITY_MAP[key]
    if key.startswith("p") and key[1:].isdigit():
        return key.upper()
    return None
