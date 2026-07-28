"""Tests for Cursor CLI response parsing."""

from shared.cursor_cli.response_parser import is_empty_shell_stdout, parse_review_response


def test_parse_json_review():
    content = """Here is the review:
{"approved": false, "summary": "Needs work", "findings": ["[ERROR] Foo.cs:1 - bug"], "suggestions": []}
"""
    data = parse_review_response(content)
    assert data["approved"] is False
    assert data["summary"] == "Needs work"
    assert "[ERROR] Foo.cs:1 - bug" in data["findings"]


def test_parse_text_review_with_verdict():
    content = """
## Summary
The change adds validation but misses edge cases.

## Findings
- blocker: src/Order.cs:42 - null reference risk
- minor: naming inconsistency

## Verdict: REQUEST_CHANGES
"""
    data = parse_review_response(content)
    assert data["approved"] is False
    assert "validation" in data["summary"].lower()
    assert any("Order.cs" in f for f in data["findings"])


def test_parse_invalid_json_does_not_crash():
    content = "{ approved: true, summary: broken json }"
    data = parse_review_response(content)
    assert "approved" in data
    assert isinstance(data["findings"], list)


def test_detect_empty_shell_json():
    content = '{"approved": true, "summary": "", "findings": [], "suggestions": []}'
    assert is_empty_shell_stdout(content) is True
    data = parse_review_response(content)
    assert data["approved"] is False
    assert "empty json" in data["summary"].lower() or "did not run" in data["summary"].lower()
    assert data["findings"]


def test_detect_ask_mode_placeholder():
    content = """
I'm ready to review as a senior engineer — focused on correctness, design, security.

Findings:
* Note: I'm in **Ask mode**, so I can read the codebase but I can't apply fixes.
"""
    data = parse_review_response(content)
    assert data["approved"] is False
    assert "did not run" in data["summary"].lower()
    assert data["findings"]
