"""Fetch git diff for a feature branch against a target branch."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitDiffError(Exception):
    pass


def _git(cmd: list[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", *cmd],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitDiffError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(cmd)} failed")
    return result.stdout.strip()


def fetch_branch_diff(
    repo_path: str | Path,
    branch_name: str,
    target_branch: str,
) -> tuple[str, list[str]]:
    """Return unified diff text and list of changed file paths."""
    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        raise GitDiffError(f"Repo path not found: {repo}")

    _git(["fetch", "origin", target_branch, branch_name], repo)

    diff_range = f"origin/{target_branch}...origin/{branch_name}"
    try:
        diff_text = _git(["diff", diff_range], repo)
        names_raw = _git(["diff", "--name-only", diff_range], repo)
    except GitDiffError:
        diff_range = f"origin/{target_branch}..origin/{branch_name}"
        diff_text = _git(["diff", diff_range], repo)
        names_raw = _git(["diff", "--name-only", diff_range], repo)

    changed_files = [line.strip() for line in names_raw.splitlines() if line.strip()]
    return diff_text, changed_files


def format_diff_for_prompt(diff_text: str, changed_files: list[str], *, max_chars: int = 120_000) -> str:
    """Format diff with file headers for LLM consumption."""
    if not diff_text.strip():
        return "(no diff — branch may be identical to target or not pushed to origin)"

    parts: list[str] = []
    if changed_files:
        parts.append("## Changed files\n" + "\n".join(f"- {f}" for f in changed_files[:200]))
        if len(changed_files) > 200:
            parts.append(f"\n… and {len(changed_files) - 200} more files")

    body = diff_text
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n\n… [diff truncated at {max_chars} chars]"
    parts.append("## Git diff\n" + body)
    return "\n\n".join(parts)
