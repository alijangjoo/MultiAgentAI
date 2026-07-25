"""Parse Cursor CLI review stdout (JSON or markdown/text)."""

from __future__ import annotations

import json
import re
from typing import Any

_INCOMPLETE_PATTERNS = (
    re.compile(r"\bask mode\b", re.I),
    re.compile(r"\bagent mode\b", re.I),
    re.compile(r"I['’]?m ready to review", re.I),
    re.compile(r"I can read the codebase and give", re.I),
    re.compile(r"switch to\s+\*?\*?Agent mode\*?\*?", re.I),
    re.compile(r"I can['’]?t apply fixes", re.I),
)


def _has_substantive_findings(findings: list[str]) -> bool:
    for item in findings:
        text = str(item).strip()
        lower = text.lower()
        if "ask mode" in lower or "agent mode" in lower:
            continue
        if re.search(r"\.(cs|py|js|ts|tsx|go|java|rb|php|sql|yaml|yml|json|md|csproj)\b", text, re.I):
            return True
        if re.search(r":\d+\b", text):
            return True
        if text.upper().startswith(("[ERROR]", "[WARNING]", "BLOCKER", "MAJOR", "MINOR")):
            return True
    return False


def is_incomplete_review_response(text: str, parsed: dict[str, Any] | None = None) -> bool:
    """True when CLI returned a preamble/disclaimer instead of reviewing the diff."""
    body = (text or "").strip()
    if not body:
        return True

    parsed = parsed or {}
    findings = parsed.get("findings") or []

    if _parse_verdict(body) is not None and _has_substantive_findings(findings):
        return False

    if any(pattern.search(body) for pattern in _INCOMPLETE_PATTERNS):
        return True

    if _parse_verdict(body) is None and not _has_substantive_findings(findings):
        lower = body.lower()
        if any(
            phrase in lower
            for phrase in (
                "ready to review",
                "produce the review",
                "clarifying questions",
                "can't apply fixes",
                "cannot apply fixes",
            )
        ):
            return True

    return False


def _normalize_review_dict(data: dict[str, Any]) -> dict[str, Any]:
    findings = data.get("findings")
    suggestions = data.get("suggestions")
    if not isinstance(findings, list):
        findings = [findings] if findings else []
    if not isinstance(suggestions, list):
        suggestions = [suggestions] if suggestions else []
    approved = data.get("approved")
    if approved is None:
        approved = not any(
            str(item).upper().startswith(("[ERROR]", "BLOCKER", "MAJOR"))
            for item in findings
        )
    return {
        "approved": bool(approved),
        "summary": str(data.get("summary") or "").strip(),
        "findings": [str(item).strip() for item in findings if str(item).strip()],
        "suggestions": [str(item).strip() for item in suggestions if str(item).strip()],
    }


def _parse_verdict(text: str) -> bool | None:
    match = re.search(
        r"verdict\s*:\s*(APPROVE|REQUEST_CHANGES|COMMENT)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    verdict = match.group(1).upper()
    if verdict == "APPROVE":
        return True
    if verdict == "REQUEST_CHANGES":
        return False
    return True


def _extract_summary(text: str) -> str:
    lines = text.splitlines()
    summary_lines: list[str] = []
    in_summary = False
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if re.match(r"^#+\s*summary\b", lower) or re.match(r"^1[\).\s]+summary\b", lower):
            in_summary = True
            continue
        if in_summary and (
            re.match(r"^#+\s", stripped)
            or re.match(r"^2[\).\s]+findings\b", lower)
            or lower.startswith("findings")
            or lower.startswith("verdict:")
        ):
            break
        if in_summary and stripped:
            summary_lines.append(stripped)
    if summary_lines:
        return " ".join(summary_lines).strip()
    chunk = re.split(r"\n\s*(?:#{1,3}\s*)?(?:findings|verdict)\b", text, maxsplit=1, flags=re.I)[0]
    parts = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
    if parts:
        return parts[0] if len(parts[0]) > 40 else " ".join(parts[:3])[:500]
    return text[:500].strip()


def _parse_text_findings(text: str) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    suggestions: list[str] = []

    severity_map = {
        "blocker": "[ERROR]",
        "major": "[ERROR]",
        "minor": "[WARNING]",
        "nit": "[SUGGESTION]",
    }

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        tagged = re.match(r"^\[(ERROR|WARNING|SUGGESTION)\]\s*(.+)", stripped, re.I)
        if tagged:
            label = tagged.group(1).upper()
            body = tagged.group(2).strip()
            entry = f"[{label}] {body}"
            (findings if label != "SUGGESTION" else suggestions).append(entry)
            continue

        bullet = re.match(
            r"^[-*•]\s*(?:(blocker|major|minor|nit)\s*[:\-—]\s*)?(.+)",
            stripped,
            re.I,
        )
        if bullet:
            severity = (bullet.group(1) or "").lower()
            body = bullet.group(2).strip()
            if severity in severity_map:
                findings.append(f"{severity_map[severity]} {body}")
            elif body:
                findings.append(body)
            continue

        numbered = re.match(
            r"^\d+[\).\s]+(?:(blocker|major|minor|nit)\s*[:\-—]\s*)?(.+)",
            stripped,
            re.I,
        )
        if numbered and numbered.group(1):
            severity = numbered.group(1).lower()
            body = numbered.group(2).strip()
            findings.append(f"{severity_map.get(severity, '[WARNING]')} {body}")

    regex_findings = re.findall(r"\[(?:ERROR|WARNING)\][^\n]+", text)
    regex_suggestions = re.findall(r"\[SUGGESTION\][^\n]+", text)
    for item in regex_findings:
        if item not in findings:
            findings.append(item)
    for item in regex_suggestions:
        if item not in suggestions:
            suggestions.append(item)

    return findings, suggestions


def parse_review_response(content: str) -> dict[str, Any]:
    """Convert Cursor CLI stdout to AgentFramework review dict."""
    text = (content or "").strip()
    if not text:
        return {
            "approved": False,
            "summary": "Empty review response",
            "findings": [],
            "suggestions": [],
        }

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict):
                return _normalize_review_dict(data)
        except json.JSONDecodeError:
            pass

    findings, suggestions = _parse_text_findings(text)
    approved = _parse_verdict(text)
    if approved is None:
        approved = not any(f.upper().startswith("[ERROR]") for f in findings)

    summary = _extract_summary(text)
    if not summary:
        summary = "Review completed (text format)."

    result = {
        "approved": bool(approved),
        "summary": summary,
        "findings": findings,
        "suggestions": suggestions,
    }
    if is_incomplete_review_response(text, result):
        return {
            "approved": False,
            "summary": (
                "Review did not run — Cursor CLI returned a placeholder message "
                "instead of analyzing the git diff."
            ),
            "findings": [
                "[ERROR] No code review was produced (Ask-mode disclaimer or missing Verdict/findings). "
                "Re-run Review after verifying the diff is included in the prompt."
            ],
            "suggestions": [
                "Check Cursor CLI logs and ensure MR diff is not empty/truncated to zero.",
            ],
        }
    return result
