"""Deterministic review rule checks on git diff (fallback when Cursor CLI returns empty JSON)."""

from __future__ import annotations

import re
from typing import Any


def _split_diff_sections(git_diff: str) -> list[tuple[str, str]]:
    text = (git_diff or "").strip()
    if not text or text == "(no changes)":
        return []

    if "### " not in text:
        return [("change", text)]

    sections: list[tuple[str, str]] = []
    parts = re.split(r"(?m)^###\s+", text)
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        path = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        sections.append((path, body))
    return sections


def _added_lines(diff_body: str) -> list[str]:
    lines: list[str] = []
    for raw in diff_body.splitlines():
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            lines.append(raw[1:])
    return lines


def _check_rr012_namespace_first(path: str, diff_body: str) -> str | None:
    if not path.lower().endswith(".cs"):
        return None
    saw_using = False
    for line in _added_lines(diff_body):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.startswith("using "):
            saw_using = True
            continue
        if stripped.startswith("namespace "):
            if saw_using:
                return (
                    f"[WARNING] {path}:0 - RR-012: namespace must be the first code construct "
                    "(using directives appear before namespace; file-scoped namespace preferred)"
                )
            return None
    return None


def _check_rr013_command_validator(path: str, all_paths: set[str]) -> str | None:
    if not path.endswith("CommandHandler.cs"):
        return None
    validator = path.replace("CommandHandler.cs", "CommandValidator.cs")
    if validator in all_paths:
        return None
    return (
        f"[ERROR] {path}:0 - RR-013: missing sibling {validator.split('/')[-1]} "
        "in the same MR (FluentValidation AbstractValidator required)"
    )


def _check_rr014_trailing_blank(path: str, diff_body: str) -> str | None:
    if not path.lower().endswith(".cs"):
        return None
    added = _added_lines(diff_body)
    if not added:
        return None
    if added[-1].strip() == "":
        return (
            f"[WARNING] {path}:0 - RR-014: file must not end with a trailing blank line "
            "(last line must be closing brace)"
        )
    for raw in diff_body.splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            if raw.rstrip("\r\n") == "+":
                return (
                    f"[WARNING] {path}:0 - RR-014: diff adds trailing blank line after closing brace"
                )
    return None


def scan_diff_for_review(git_diff: str) -> dict[str, Any]:
    """Build a review JSON dict from deterministic diff rule checks."""
    sections = _split_diff_sections(git_diff)
    all_paths = {path for path, _ in sections}
    findings: list[str] = []
    suggestions: list[str] = []

    for path, body in sections:
        rr012 = _check_rr012_namespace_first(path, body)
        if rr012:
            findings.append(rr012)
        rr013 = _check_rr013_command_validator(path, all_paths)
        if rr013:
            findings.append(rr013)
        rr014 = _check_rr014_trailing_blank(path, body)
        if rr014:
            findings.append(rr014)

    blocking = any(item.upper().startswith("[ERROR]") for item in findings)
    if findings:
        summary = (
            "Deterministic Sentinel rule scan found violations in the MR diff "
            "(Cursor CLI returned empty JSON; fallback scanner used)."
        )
    else:
        summary = (
            "Cursor CLI returned empty JSON and deterministic scan found no known rule violations."
        )

    return {
        "approved": not blocking and not findings,
        "summary": summary,
        "findings": findings,
        "suggestions": suggestions,
    }
