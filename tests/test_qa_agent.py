"""Tests for QA Agent prompt, parser, and templates."""

import json

import pytest

from api.services.qa_service import resolve_qa_repo_path
from shared.qa.models import QaContext
from shared.qa.prompt_builder import build_qa_prompt
from shared.qa.response_parser import parse_qa_response
from shared.qa.git_diff import format_diff_for_prompt
from slices.qa.template_loader import apply_qa_template_placeholders, is_template_placeholder, load_acceptance_criteria_template


def test_build_qa_prompt_includes_diff_and_ac():
    ctx = QaContext(
        branch_name="feature/VEN-100-login",
        target_branch="develop",
        task_key="VEN-100",
        git_diff="## Git diff\n+ new code",
        acceptance_criteria="AC-1: User can login",
        feature_brief="Login feature",
        language="fa",
    )
    prompt = build_qa_prompt(ctx)
    assert "VEN-100" in prompt
    assert "AC-1" in prompt
    assert "new code" in prompt
    assert "test_cases" in prompt


def test_parse_qa_response_json():
    payload = {
        "ready": True,
        "verdict": "PASS",
        "summary": "All good",
        "test_cases": [{"id": "TC-1", "title": "Login success", "steps": ["Open app"], "expected_result": "OK"}],
        "use_cases": [{"id": "UC-1", "actor": "User", "goal": "Login", "main_flow": ["Enter credentials"]}],
        "critical_flows": ["Payment"],
        "ac_coverage": [{"criterion_id": "AC-1", "criterion": "Login works", "status": "covered"}],
        "gaps": [],
        "automation_suggestions": ["pytest test_login.py"],
        "missing_inputs": [],
    }
    result = parse_qa_response(json.dumps(payload))
    assert result.verdict == "PASS"
    assert result.ready is True
    assert len(result.test_cases) == 1
    assert result.test_cases[0].title == "Login success"
    assert len(result.use_cases) == 1
    assert result.ac_coverage[0].status == "covered"


def test_is_template_placeholder_detects_tbd():
    assert is_template_placeholder("TBD")
    assert is_template_placeholder("| | | |")
    assert not is_template_placeholder(
        "## AC\n| AC-1 | User must login with valid credentials and see dashboard | Must | Yes |\n"
        "Given user exists When credentials valid Then dashboard shown\n" * 3
    )


def test_apply_qa_template_placeholders():
    tpl = "Branch: {BRANCH_NAME} Key: {JIRA_KEY} Date: {DATE}"
    out = apply_qa_template_placeholders(tpl, branch_name="feature/x", jira_key="VEN-1")
    assert "feature/x" in out
    assert "VEN-1" in out


def test_format_diff_for_prompt():
    text = format_diff_for_prompt("diff body", ["a.py", "b.py"])
    assert "a.py" in text
    assert "diff body" in text


def test_load_acceptance_criteria_template_exists():
    tpl = load_acceptance_criteria_template()
    assert "Acceptance Criteria" in tpl or "AC-1" in tpl


def test_resolve_qa_repo_path_prefers_explicit(monkeypatch):
    monkeypatch.setenv("CURSOR_REPO_PATH", r"C:\old\repo")
    from core.config import get_settings

    get_settings.cache_clear()
    explicit = r"C:\Users\me\source\repos\dizi_v2\dizi"
    assert resolve_qa_repo_path(explicit) == explicit
    get_settings.cache_clear()


def test_resolve_qa_repo_path_raises_when_unset(monkeypatch):
    monkeypatch.setenv("CURSOR_REPO_PATH", "")
    from core.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(ValueError, match="Local repo path"):
        resolve_qa_repo_path(None)
    get_settings.cache_clear()
