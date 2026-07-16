import pytest

from shared.integrations.jira_helpers import (
    extract_text_from_adf,
    format_jira_estimate,
    normalize_jira_description,
    pick_subtask_issue_type,
)


def test_extract_text_from_adf():
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello PRD"}],
            }
        ],
    }
    assert "Hello PRD" in extract_text_from_adf(adf)


def test_normalize_jira_description_string():
    assert normalize_jira_description("plain text") == "plain text"


def test_format_jira_estimate():
    assert format_jira_estimate(4.5) == "4h"
    assert format_jira_estimate(0.5) == "1h"


def test_pick_subtask_issue_type():
    meta = {
        "issueTypes": [
            {"name": "Story", "subtask": False},
            {"name": "Sub-task", "subtask": True},
        ]
    }
    assert pick_subtask_issue_type(meta) == "Sub-task"
