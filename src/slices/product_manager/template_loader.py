from datetime import date
from pathlib import Path

from core.config import get_settings


def load_prd_template() -> str:
    settings = get_settings()
    template_path = Path(settings.prd_template_path)
    if not template_path.is_absolute():
        root = Path(__file__).resolve().parents[3]
        template_path = root / template_path
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return "# PRD\n\n## Title\n{TITLE}\n"


def apply_prd_placeholders(
    template: str,
    *,
    title: str,
    author: str = "Meridian Agent",
    stakeholders: str = "",
    tech_lead: str = "",
    jira_key: str = "TBD",
) -> str:
    today = date.today().isoformat()
    return (
        template.replace("{TITLE}", title)
        .replace("{AUTHOR}", author)
        .replace("{STAKEHOLDERS}", stakeholders or "TBD")
        .replace("{TECH_LEAD}", tech_lead or "TBD")
        .replace("{JIRA_KEY}", jira_key)
        .replace("{DATE}", today)
    )
