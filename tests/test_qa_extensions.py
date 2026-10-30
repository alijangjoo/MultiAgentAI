"""Tests for QA export, quality gate, and metrics."""

import json

from shared.qa.exporters import export_cypress_spec, export_pytest_module, export_test_cases_markdown
from shared.qa.models import QaResult, TestCaseItem
from shared.qa.quality_gate import check_qa_gate


def _sample_qa() -> QaResult:
    return QaResult(
        ready=True,
        verdict="PASS",
        summary="Login works",
        test_cases=[
            TestCaseItem(
                id="TC-1",
                title="Successful login",
                steps=["Open login page", "Enter credentials"],
                expected_result="Dashboard shown",
                priority="critical",
            )
        ],
    )


def test_export_pytest_module():
    qa = _sample_qa()
    path, content = export_pytest_module(qa, task_key="VEN-100", branch_name="feature/VEN-100-login")
    assert path.startswith("tests/generated/test_ven-100")
    assert "def test_tc_1" in content
    assert "pytest" in content
    assert "Dashboard shown" in content


def test_export_cypress_spec():
    qa = _sample_qa()
    path, content = export_cypress_spec(qa, task_key="VEN-100", branch_name="feature/VEN-100-login")
    assert path.startswith("cypress/e2e/ven-100")
    assert "describe(" in content
    assert "TC-1" in content


def test_export_markdown():
    md = export_test_cases_markdown(_sample_qa(), task_key="VEN-100", branch_name="feature/x", run_id="run-1")
    assert "VEN-100" in md
    assert "TC-1" in md


def test_quality_gate_pass():
    result = check_qa_gate("PASS", ready=True, gate_enabled=True)
    assert result["passed"] is True


def test_quality_gate_fail():
    result = check_qa_gate("FAIL", gate_enabled=True)
    assert result["passed"] is False


def test_quality_gate_disabled():
    result = check_qa_gate("FAIL", gate_enabled=False)
    assert result["passed"] is True
