"""Tests for Cursor CLI review module."""

from shared.cursor_cli.context_builder import build_review_context
from shared.cursor_cli.model_utils import normalize_cursor_cli_model
from shared.cursor_cli.models import ReviewContext
from shared.cursor_cli.prompt_builder import build_review_prompt
from shared.models.domain import MergeRequestInfo


def _sample_mr() -> MergeRequestInfo:
    return MergeRequestInfo(
        iid=42,
        title="feat(VEN-123): add order validation",
        source_branch="feature/ven-123-order-validation",
        target_branch="dev-oms-v2",
        url="https://gitlab.example/mrs/42",
    )


def test_build_review_prompt_matches_cursor_review_agent_shape():
    context = ReviewContext(
        title="Test MR",
        description="Implements validation",
        git_diff="--- a/Foo.cs\n+++ b/Foo.cs\n",
        specs="## Code Specs\nUse FluentValidation",
        review_rules="RR-001 [ERROR] No secrets",
        extra_context={"tech_stack": ".NET 8"},
        language="en",
    )
    prompt = build_review_prompt(context, output_format="text")

    assert "Test MR" in prompt
    assert "Implements validation" in prompt
    assert "FluentValidation" in prompt
    assert "RR-001" in prompt
    assert "Tech Stack" in prompt
    assert "Foo.cs" in prompt
    assert "Verdict: APPROVE" in prompt or "APPROVE | REQUEST_CHANGES" in prompt


def test_normalize_cursor_cli_model_remaps_9router_ids():
    assert normalize_cursor_cli_model("cu/claude-4.5-sonnet") == "composer-2.5"
    assert normalize_cursor_cli_model("gpt-4o") == "composer-2.5"
    assert normalize_cursor_cli_model("composer-2.5-fast") == "composer-2.5"
    assert normalize_cursor_cli_model("composer-2.5") == "composer-2.5"


def test_should_fallback_on_unavailable():
    from shared.cursor_cli.fallback import should_fallback_from_cursor_cli

    assert should_fallback_from_cursor_cli("", "Error: [unavailable]") is True


def test_should_not_fallback_on_permission_denied():
    from shared.cursor_cli.fallback import (
        should_fallback_from_cursor_cli,
        summarize_cursor_cli_failure,
    )

    err = "RetriableError: [permission_denied] Cu"
    assert should_fallback_from_cursor_cli(err, "") is False
    summary = summarize_cursor_cli_failure(err, "")
    assert "CURSOR_API_KEY" in summary


def test_build_command_stays_short_on_windows_for_large_prompt(monkeypatch):
    monkeypatch.setattr("shared.cursor_cli.runner.os.name", "nt")
    from core.config import Settings
    from shared.cursor_cli.runner import _build_command_base, _prompt_fits_argv

    huge = "x" * 50_000
    base = _build_command_base(
        cli_bin="agent.cmd",
        settings=Settings(),
        model="composer-2.5",
        workspace="C:\\repo",
        output_format="text",
        mode="ask",
    )
    assert _prompt_fits_argv(base, huge) is False
    joined = " ".join(base)
    assert len(joined) < 500
    assert huge not in joined


def test_build_review_context_omits_specs_by_default():
    from slices.knowledge.review_package import ReviewKnowledgePackage

    kp = ReviewKnowledgePackage(
        task_key="VEN-123",
        prd="PRD body should not appear",
        adrs="ADR body",
        code_specs="Spec body should not appear",
        architecture_specs="Arch body should not appear",
        source_context="Source body",
        review_rules="Rule body",
        ubiquitous_language="UL body",
        tech_stack=".NET 8",
    )
    context = build_review_context(
        mr=_sample_mr(),
        task_key="VEN-123",
        development_summary="Summary text",
        code_context="",
        mr_changes=[{"new_path": "src/Foo.cs", "diff": "+ code"}],
        knowledge_package=kp,
        include_specs=False,
    )

    assert context.specs is None
    assert "PRD body" not in (context.specs or "")
    assert context.review_rules == "Rule body"
    assert "Foo.cs" in context.git_diff


def test_build_review_context_maps_knowledge_fields():
    from slices.knowledge.review_package import ReviewKnowledgePackage

    kp = ReviewKnowledgePackage(
        task_key="VEN-123",
        prd="PRD body",
        adrs="ADR body",
        code_specs="Spec body",
        architecture_specs="Arch body",
        source_context="Source body",
        review_rules="Rule body",
        ubiquitous_language="UL body",
        tech_stack=".NET 8",
    )
    context = build_review_context(
        mr=_sample_mr(),
        task_key="VEN-123",
        development_summary="Summary text",
        code_context="",
        mr_changes=[{"new_path": "src/Foo.cs", "diff": "+ code"}],
        knowledge_package=kp,
        include_specs=True,
    )

    assert context.title == "feat(VEN-123): add order validation"
    assert context.description == "Summary text"
    assert "PRD body" in (context.specs or "")
    assert "Spec body" in (context.specs or "")
    assert context.review_rules == "Rule body"
    assert context.extra_context is not None
    assert context.extra_context["adrs"] == "ADR body"
    assert context.extra_context["jira_ticket"] == "VEN-123"
    assert "Foo.cs" in context.git_diff
