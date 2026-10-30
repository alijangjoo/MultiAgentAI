"""QA quality gate — block release pipeline when QA verdict fails."""

from __future__ import annotations

from core.config import get_settings

PASSING_VERDICTS = frozenset({"PASS", "PASS_WITH_GAPS"})


def allowed_verdicts() -> set[str]:
    settings = get_settings()
    raw = (settings.qa_gate_allowed_verdicts or "PASS,PASS_WITH_GAPS").strip()
    return {v.strip().upper() for v in raw.split(",") if v.strip()}


def check_qa_gate(
    verdict: str | None,
    *,
    ready: bool | None = None,
    gate_enabled: bool | None = None,
) -> dict:
    """Return gate result: passed, verdict, message."""
    settings = get_settings()
    enabled = settings.qa_gate_enabled if gate_enabled is None else gate_enabled
    normalized = (verdict or "PENDING").upper()
    allowed = allowed_verdicts()

    if not enabled:
        return {
            "passed": True,
            "gate_enabled": False,
            "verdict": normalized,
            "message": "QA gate disabled",
        }

    if normalized not in allowed:
        return {
            "passed": False,
            "gate_enabled": True,
            "verdict": normalized,
            "allowed_verdicts": sorted(allowed),
            "message": f"QA gate failed: verdict {normalized} not in {sorted(allowed)}",
        }

    if ready is False and normalized == "PASS":
        return {
            "passed": False,
            "gate_enabled": True,
            "verdict": normalized,
            "allowed_verdicts": sorted(allowed),
            "message": "QA gate failed: ready=false despite PASS verdict",
        }

    return {
        "passed": True,
        "gate_enabled": True,
        "verdict": normalized,
        "allowed_verdicts": sorted(allowed),
        "message": f"QA gate passed ({normalized})",
    }
