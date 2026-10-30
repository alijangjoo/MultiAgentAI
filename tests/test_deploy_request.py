"""Tests for Deploy Request helpers."""

from shared.utils.jira_key_from_branch import extract_jira_key_from_branch
from shared.utils.priority_map import jira_priority_to_pn
from slices.deploy_request.message_builder import build_deploy_message
from slices.deploy_request.models.state import DeployRequest
from slices.deploy_request.pipeline_context import all_required_jobs_succeeded


def test_extract_jira_key_from_feature_branch():
    assert (
        extract_jira_key_from_branch("feature/ven-100-create-api-for-contract")
        == "VEN-100"
    )


def test_extract_jira_key_case_and_path():
    assert extract_jira_key_from_branch("Feature/VEN-900-fix-cache") == "VEN-900"
    assert extract_jira_key_from_branch("bugfix/abc-12-something") == "ABC-12"


def test_extract_jira_key_missing():
    assert extract_jira_key_from_branch("feature/hotfix-no-ticket") is None
    assert extract_jira_key_from_branch("") is None
    assert extract_jira_key_from_branch(None) is None


def test_jira_priority_mapping():
    assert jira_priority_to_pn("High") == "P1"
    assert jira_priority_to_pn("Medium") == "P2"
    assert jira_priority_to_pn("Low") == "P3"
    assert jira_priority_to_pn("Lowest") == "P4"
    assert jira_priority_to_pn("p1") == "P1"
    assert jira_priority_to_pn(None) is None


def test_build_deploy_message_contains_required_sections():
    req = DeployRequest(
        run_id="run-1",
        app_name="Dizi",
        version="v0.173.0-dev",
        mr_url="https://git.tapsifood.cloud/ofd/backend/dizi/-/merge_requests/100",
        pipeline_url="https://git.tapsifood.cloud/ofd/backend/dizi/-/pipelines/76328",
        priority="P1",
        publish_at="2026-07-12 14:00",
        changes_url="https://git.example/mr/1/diffs",
        endpoints=["Dizi.Endpoints.BackOfficeApp.Api", "Dizi.Endpoints.VendorApp.Api"],
        service_name="Dizi service",
        jira_title="Create API for contract",
        jira_url="https://desk.tapsifood.cloud/browse/VEN-100",
    )
    msg = build_deploy_message(req)
    assert "Deploy Request" in msg
    assert "Service: [Dizi] [v0.173.0-dev]" in msg
    assert "MR/GitLab Link: [https://git.tapsifood.cloud/ofd/backend/dizi/-/merge_requests/100]" in msg
    assert "Priority: [P1]" in msg
    assert "Impacted Areas (What changed?):" in msg
    assert "Dizi.Endpoints.BackOfficeApp.Api" in msg
    assert "VEN-100" in msg
    assert "Developer Approval: Approved" in msg
    assert "@ebrahimi.mahrokh" in msg


def test_all_required_jobs_ignores_superseded_retries():
    jobs = [
        {"id": 1, "name": "build", "status": "failed"},
        {"id": 2, "name": "build", "status": "success"},
        {"id": 3, "name": "deploy", "status": "success"},
    ]
    assert all_required_jobs_succeeded(jobs, pipeline_status="success") is True


def test_build_deploy_message_defaults():
    req = DeployRequest(run_id="run-2", app_name="Dizi")
    msg = build_deploy_message(req)
    assert "API(s): [dizi api]" in msg
    assert "Service(s): [Dizi service]" in msg
