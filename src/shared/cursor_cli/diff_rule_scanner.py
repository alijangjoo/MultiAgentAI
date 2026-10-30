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


def _reconstruct_new_file(diff_body: str) -> list[str]:
    """Best-effort full new file content from unified diff added lines."""
    return [line for line in _added_lines(diff_body) if line is not None]


def _namespace_hint(path: str) -> str:
    clean = path.replace("\\", "/")
    if clean.startswith("src/"):
        clean = clean[4:]
    dir_part = "/".join(clean.split("/")[:-1])
    return f"namespace Dizi.{dir_part.replace('/', '.')};"


def _check_rr012_namespace_first(path: str, diff_body: str) -> tuple[str | None, str | None]:
    if not path.lower().endswith(".cs"):
        return None, None
    file_lines = _reconstruct_new_file(diff_body)
    if not file_lines:
        return None, None

    saw_using = False
    namespace_line = 0
    for idx, line in enumerate(file_lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.startswith("using "):
            saw_using = True
            continue
        if stripped.startswith("namespace "):
            namespace_line = idx
            if saw_using:
                finding = (
                    f"[ERROR] {path}:{namespace_line} - RR-012: namespace declaration must be the "
                    "first code construct (before using directives). File has using directives before namespace."
                )
                suggestion = (
                    f"[SUGGESTION] {path}:{namespace_line} - Move namespace declaration before using "
                    f"directives using file-scoped namespace (e.g., {_namespace_hint(path)})."
                )
                return finding, suggestion
            return None, None
    return None, None


def _check_rr013_command_validator(path: str, all_paths: set[str]) -> tuple[str | None, str | None]:
    if not path.endswith("CommandHandler.cs"):
        return None, None
    validator_name = path.replace("CommandHandler.cs", "CommandValidator.cs")
    if validator_name in all_paths:
        return None, None
    validator_base = validator_name.split("/")[-1]
    finding = (
        f"[ERROR] {path}:1 - RR-013: Every *CommandHandler must have a matching *CommandValidator. "
        f"No {validator_base.replace('.cs', '')} was found in the diff."
    )
    suggestion = (
        f"[SUGGESTION] {path}:1 - Add {validator_base} with FluentValidation "
        f"AbstractValidator<{path.split('/')[-1].replace('CommandHandler.cs', 'Command')}."
    )
    return finding, suggestion


def _check_rr014_trailing_blank(path: str, diff_body: str) -> tuple[str | None, str | None]:
    if not path.lower().endswith(".cs"):
        return None, None
    file_lines = _reconstruct_new_file(diff_body)
    if not file_lines:
        return None, None

    trailing_blank = False
    last_code_line = 0
    for idx, line in enumerate(file_lines, start=1):
        if line.strip():
            last_code_line = idx
        elif last_code_line > 0:
            trailing_blank = True

    if not trailing_blank:
        for raw in diff_body.splitlines():
            if raw.startswith("+") and not raw.startswith("+++") and raw.rstrip("\r\n") == "+":
                trailing_blank = True
                last_code_line = max(last_code_line, len(file_lines))
                break

    if not trailing_blank:
        return None, None

    line_ref = last_code_line or len(file_lines)
    finding = (
        f"[WARNING] {path}:{line_ref} - RR-014: File ends with a trailing blank line "
        "after the final closing brace."
    )
    suggestion = (
        f"[SUGGESTION] {path}:{line_ref} - Remove trailing blank line after the final closing brace."
    )
    return finding, suggestion


def scan_diff_for_review(git_diff: str) -> dict[str, Any]:
    """Build a review JSON dict from deterministic diff rule checks."""
    sections = _split_diff_sections(git_diff)
    all_paths = {path for path, _ in sections}
    findings: list[str] = []
    suggestions: list[str] = []

    for path, body in sections:
        rr012_finding, rr012_suggestion = _check_rr012_namespace_first(path, body)
        if rr012_finding:
            findings.append(rr012_finding)
        if rr012_suggestion:
            suggestions.append(rr012_suggestion)

        rr013_finding, rr013_suggestion = _check_rr013_command_validator(path, all_paths)
        if rr013_finding:
            findings.append(rr013_finding)
        if rr013_suggestion:
            suggestions.append(rr013_suggestion)

        rr014_finding, rr014_suggestion = _check_rr014_trailing_blank(path, body)
        if rr014_finding:
            findings.append(rr014_finding)
        if rr014_suggestion:
            suggestions.append(rr014_suggestion)

    blocking = any(item.upper().startswith("[ERROR]") for item in findings)
    if findings:
        summary = (
            "Review of the diff reveals multiple violations: "
            + ", ".join(
                label
                for label, present in (
                    ("missing mandatory validator for the new command handler", any("RR-013" in f for f in findings)),
                    (
                        "namespace declaration not being the first code construct",
                        any("RR-012" in f for f in findings),
                    ),
                    ("trailing blank lines in new files", any("RR-014" in f for f in findings)),
                )
                if present
            )
            + "."
        ).replace(": ,", ":").replace(", .", ".")
        if summary.endswith(": ."):
            summary = (
                "Review of the diff reveals rule violations in the MR diff "
                "(deterministic Sentinel scan; Cursor CLI did not return substantive JSON)."
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


def merge_review_with_diff_scan(parsed: dict[str, Any], git_diff: str) -> dict[str, Any]:
    """Merge CLI/LLM review with deterministic diff scan (prefer scanner when CLI is empty)."""
    from shared.cursor_cli.response_parser import is_incomplete_review_response

    scanned = scan_diff_for_review(git_diff)
    if not (git_diff or "").strip():
        return parsed

    findings = parsed.get("findings") or []
    cli_incomplete = is_incomplete_review_response(str(parsed.get("summary") or ""), parsed)
    cli_has_findings = bool(findings)

    if cli_incomplete or not cli_has_findings:
        if scanned.get("findings") or scanned.get("suggestions"):
            return scanned
        return parsed

    if not scanned.get("findings") and not scanned.get("suggestions"):
        return parsed

    merged_findings = list(parsed.get("findings") or [])
    merged_suggestions = list(parsed.get("suggestions") or [])
    for item in scanned.get("findings") or []:
        if item not in merged_findings:
            merged_findings.append(item)
    for item in scanned.get("suggestions") or []:
        if item not in merged_suggestions:
            merged_suggestions.append(item)

    blocking = any(str(item).upper().startswith("[ERROR]") for item in merged_findings)
    summary = str(parsed.get("summary") or "").strip() or scanned.get("summary") or ""
    return {
        "approved": not blocking,
        "summary": summary,
        "findings": merged_findings,
        "suggestions": merged_suggestions,
    }
