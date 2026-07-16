"""Extract Jira issue keys from Git branch names."""

from __future__ import annotations

import re

# feature/ven-100-create-api-for-contract → VEN-100
_BRANCH_JIRA_RE = re.compile(
    r"(?:^|/)([A-Za-z][A-Za-z0-9]+)-(\d+)(?:-|$|/)",
    re.IGNORECASE,
)


def extract_jira_key_from_branch(branch_name: str | None) -> str | None:
    if not branch_name:
        return None
    match = _BRANCH_JIRA_RE.search(branch_name.strip())
    if not match:
        return None
    return f"{match.group(1).upper()}-{match.group(2)}"
