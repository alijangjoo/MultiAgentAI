"""Load QA input templates with branch/task placeholders."""

from datetime import date
from pathlib import Path

from core.config import get_settings


def _resolve_template(relative_path: str) -> Path:
    settings = get_settings()
    template_path = Path(relative_path)
    if not template_path.is_absolute():
        root = Path(__file__).resolve().parents[3]
        template_path = root / template_path
    return template_path


def load_acceptance_criteria_template() -> str:
    settings = get_settings()
    path = _resolve_template(settings.qa_acceptance_criteria_template_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "# Acceptance Criteria\n\n| ID | Criterion |\n|----|-----------|\n| AC-1 | TBD |\n"


def load_feature_brief_template() -> str:
    settings = get_settings()
    path = _resolve_template(settings.qa_feature_brief_template_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "# Feature Brief\n\n## Problem\nTBD\n"


def apply_qa_template_placeholders(
    template: str,
    *,
    branch_name: str = "",
    target_branch: str = "",
    jira_key: str = "TBD",
) -> str:
    today = date.today().isoformat()
    return (
        template.replace("{BRANCH_NAME}", branch_name or "feature/your-branch")
        .replace("{TARGET_BRANCH}", target_branch or "develop")
        .replace("{JIRA_KEY}", jira_key)
        .replace("{DATE}", today)
    )


def is_template_placeholder(text: str | None) -> bool:
    """Heuristic: user has not filled meaningful QA inputs."""
    if not text or not text.strip():
        return True
    lowered = text.lower()
    markers = ("tbd", "<!--", "your-branch", "feature/your-branch", "| | | |")
    hits = sum(1 for m in markers if m in lowered)
    non_empty_lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if hits >= 2 and len(non_empty_lines) < 5:
        return True
    if len(text.strip()) < 80:
        return True
    return False
