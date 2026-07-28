from pathlib import Path

from shared.cursor_cli.models import ReviewContext
from shared.cursor_cli.prompt_builder import build_review_prompt, build_skill_review_prompt
from shared.cursor_cli.review_workspace import materialize_review_skill


def test_build_skill_review_prompt_requests_json_only() -> None:
    context = ReviewContext(
        title="Fix domain reference",
        git_diff="--- a/Foo.cs\n+++ b/Foo.cs\n",
        use_review_skill=True,
    )
    prompt = build_skill_review_prompt(context, output_format="text")

    assert "sentinel-review" in prompt
    assert "approved" in prompt
    assert "Verdict:" not in prompt


def test_build_skill_review_prompt_includes_review_rules():
    context = ReviewContext(
        git_diff="+ change",
        review_rules="RR-012 namespace rule",
        use_review_skill=True,
    )
    prompt = build_skill_review_prompt(context)

    assert "Active Review Rules" in prompt
    assert "RR-012 namespace rule" in prompt
    assert "Mandatory checklist" in prompt


def test_build_review_prompt_switches_to_skill_mode() -> None:
    context = ReviewContext(
        git_diff="+ change",
        review_rules="RR-001 inline rule",
        use_review_skill=True,
    )
    prompt = build_review_prompt(context)

    assert "sentinel-review" in prompt
    assert "RR-001 inline rule" in prompt
    assert "Mandatory checklist" in prompt


def test_materialize_review_skill_writes_skill_md(tmp_path: Path) -> None:
    body = "---\nname: sentinel-review\n---\n\n# Skill\n"
    skill_path = materialize_review_skill(tmp_path, body)

    assert skill_path == tmp_path / ".cursor" / "skills" / "sentinel-review" / "SKILL.md"
    assert skill_path.read_text(encoding="utf-8") == body
