"""RTK (Rust Token Killer) integration for Sentinel code review prompts.

Compresses git diff / MR diff text before embedding in the Cursor CLI prompt,
while preserving a raw copy for deterministic rule scanning (RR-012/013/014).

See: docs/RTK_REVIEW.md
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.config import Settings, get_settings
from shared.utils.token_count import count_text_tokens

CompressMethod = Literal["rtk_git", "rtk_diff", "internal", "none"]


@dataclass(frozen=True)
class DiffCompressResult:
    compressed: str
    raw: str
    method: CompressMethod
    raw_chars: int
    compressed_chars: int
    raw_tokens: int
    compressed_tokens: int
    savings_pct: float

    @property
    def tokens_saved(self) -> int:
        return max(0, self.raw_tokens - self.compressed_tokens)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "raw_tokens": self.raw_tokens,
            "compressed_tokens": self.compressed_tokens,
            "tokens_saved": self.tokens_saved,
            "savings_pct": self.savings_pct,
            "raw_chars": self.raw_chars,
            "compressed_chars": self.compressed_chars,
            "note": self.note,
        }

    @property
    def note(self) -> str:
        if self.method == "none" or self.savings_pct < 1:
            return "no compression applied"
        return (
            f"{self.method}: {self.raw_tokens:,} → {self.compressed_tokens:,} tokens "
            f"({self.savings_pct:.0f}% smaller)"
        )


def fetch_rtk_cli_gain_json(*, timeout: int = 15) -> dict | None:
    """Run `rtk gain --all --format json` when RTK is installed."""
    if not is_rtk_available():
        return None
    try:
        completed = _run_rtk(["gain", "--all", "--format", "json"], timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return {
            "available": True,
            "error": (completed.stderr or completed.stdout or "rtk gain failed")[:500],
        }
    import json

    text = (completed.stdout or "").strip()
    if not text:
        return {"available": True, "raw": ""}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data["available"] = True
            return data
    except json.JSONDecodeError:
        pass
    return {"available": True, "raw": text[:8000]}


def resolve_rtk_bin(rtk_bin: str | None = None) -> str | None:
    name = (rtk_bin or get_settings().rtk_bin or "rtk").strip() or "rtk"
    if Path(name).is_file():
        return name
    resolved = shutil.which(name)
    if resolved:
        return resolved
    if name.lower() == "rtk":
        local = Path.home() / ".local" / "bin" / "rtk.exe"
        if local.is_file():
            return str(local)
    return None


def is_rtk_available(rtk_bin: str | None = None) -> bool:
    return resolve_rtk_bin(rtk_bin) is not None


def _run_rtk(args: list[str], *, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    bin_path = resolve_rtk_bin()
    if not bin_path:
        raise FileNotFoundError("rtk binary not found")
    return subprocess.run(
        [bin_path, *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def compress_git_diff_rtk(
    *,
    repo_path: Path,
    base_ref: str,
    head_ref: str = "HEAD",
    timeout: int = 60,
) -> str | None:
    """Run `rtk git diff base...head` inside a git repo/worktree."""
    if not repo_path.is_dir():
        return None
    ref_range = f"{base_ref}...{head_ref}"
    branch = base_ref.replace("origin/", "").strip()
    if branch and branch != base_ref:
        try:
            subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=min(timeout, 45),
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
    try:
        result = _run_rtk(["git", "diff", ref_range], cwd=repo_path, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode not in (0, 1):
        return None
    out = (result.stdout or "").strip()
    return out or None


def _format_rtk_git_diff_as_mr_sections(diff_text: str) -> str:
    """Convert unified diff from rtk git diff into ### path sections for scanners."""
    if not diff_text.strip():
        return "(no changes)"
    if diff_text.strip().startswith("### "):
        return diff_text.strip()

    sections: list[str] = []
    current_path = ""
    current_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_path and current_lines:
                sections.append(f"### {current_path}\n" + "\n".join(current_lines))
            match = re.search(r" b/(.+)$", line)
            current_path = match.group(1) if match else "unknown"
            current_lines = [line]
            continue
        if current_path:
            current_lines.append(line)

    if current_path and current_lines:
        sections.append(f"### {current_path}\n" + "\n".join(current_lines))

    return "\n\n".join(sections) if sections else diff_text


def _compact_unified_hunk(hunk_lines: list[str], *, max_context: int = 3) -> list[str]:
    """RTK-inspired: keep all +/- lines; trim context (space-prefixed) lines."""
    if not hunk_lines:
        return hunk_lines

    header = hunk_lines[0]
    body = hunk_lines[1:]
    if not body:
        return hunk_lines

    result_body: list[str] = []
    i = 0
    while i < len(body):
        line = body[i]
        if line.startswith(("+", "-")):
            result_body.append(line)
            i += 1
            continue
        # context block
        ctx_start = i
        while i < len(body) and body[i].startswith(" "):
            i += 1
        ctx_block = body[ctx_start:i]
        if not ctx_block:
            continue
        if len(ctx_block) <= max_context * 2:
            result_body.extend(ctx_block)
        else:
            result_body.extend(ctx_block[:max_context])
            omitted = len(ctx_block) - max_context * 2
            result_body.append(f" ... ({omitted} context lines omitted) ...")
            result_body.extend(ctx_block[-max_context:])

    return [header, *result_body]


def _compact_file_diff(diff_body: str, *, max_context: int = 3) -> str:
    lines = diff_body.splitlines()
    out: list[str] = []
    hunk: list[str] = []

    def flush_hunk() -> None:
        nonlocal hunk
        if hunk:
            out.extend(_compact_unified_hunk(hunk, max_context=max_context))
            hunk = []

    for line in lines:
        if line.startswith("@@"):
            flush_hunk()
            hunk = [line]
        elif hunk:
            hunk.append(line)
        else:
            # file headers — keep
            if line.startswith(("---", "+++", "diff --git", "index ")):
                out.append(line)
            elif line.strip():
                out.append(line)
    flush_hunk()
    return "\n".join(out)


def compress_mr_diff_internal(diff_text: str, *, max_context: int = 3) -> str:
    """Fallback compressor when RTK binary is unavailable."""
    text = (diff_text or "").strip()
    if not text or text == "(no changes)":
        return text or "(no changes)"

    if "### " not in text:
        return _compact_file_diff(text, max_context=max_context)

    parts = re.split(r"(?m)^###\s+", text)
    blocks: list[str] = []
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        lines = chunk.splitlines()
        path = lines[0].strip()
        body = "\n".join(lines[1:])
        compact_body = _compact_file_diff(body, max_context=max_context)
        blocks.append(f"### {path}\n{compact_body}".strip())

    header = "[diff compacted for review — all +/- lines kept; context trimmed]\n\n"
    return header + "\n\n".join(blocks)


def compress_mr_diff_rtk_pipe(diff_text: str, *, timeout: int = 30) -> str | None:
    """Try RTK on a temp patch file (best-effort)."""
    if not is_rtk_available():
        return None
    text = (diff_text or "").strip()
    if not text or text == "(no changes)":
        return text

    with tempfile.TemporaryDirectory(prefix="agentframework-rtk-") as tmp:
        patch_path = Path(tmp) / "review.patch"
        patch_path.write_text(text, encoding="utf-8")
        try:
            result = _run_rtk(["diff", str(patch_path), str(patch_path)], timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode not in (0, 1):
            return None
        out = (result.stdout or "").strip()
        return out or None


def compress_diff_for_review(
    diff_text: str,
    *,
    settings: Settings | None = None,
    repo_path: Path | str | None = None,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
) -> DiffCompressResult:
    """Compress MR/git diff for LLM prompt; always return raw copy for scanners."""
    cfg = settings or get_settings()
    raw = (diff_text or "").strip() or "(no changes)"
    raw_tokens = count_text_tokens(raw)

    if not cfg.cursor_review_use_rtk:
        return DiffCompressResult(
            compressed=raw,
            raw=raw,
            method="none",
            raw_chars=len(raw),
            compressed_chars=len(raw),
            raw_tokens=raw_tokens,
            compressed_tokens=raw_tokens,
            savings_pct=0.0,
        )

    compressed: str | None = None
    method: CompressMethod = "internal"

    if repo_path and base_ref:
        rtk_git = compress_git_diff_rtk(
            repo_path=Path(repo_path),
            base_ref=base_ref,
            head_ref=head_ref,
            timeout=cfg.rtk_timeout_seconds,
        )
        if rtk_git:
            compressed = _format_rtk_git_diff_as_mr_sections(rtk_git)
            method = "rtk_git"

    if compressed is None:
        rtk_pipe = compress_mr_diff_rtk_pipe(raw, timeout=cfg.rtk_timeout_seconds)
        if rtk_pipe:
            compressed = rtk_pipe
            method = "rtk_diff"

    if compressed is None:
        compressed = compress_mr_diff_internal(
            raw,
            max_context=cfg.cursor_review_rtk_max_context_lines,
        )
        method = "internal"

    compressed = compressed.strip() or raw
    compressed_tokens = count_text_tokens(compressed)
    savings = 0.0
    if raw_tokens > 0:
        savings = max(0.0, (1.0 - compressed_tokens / raw_tokens) * 100.0)

    return DiffCompressResult(
        compressed=compressed,
        raw=raw,
        method=method,
        raw_chars=len(raw),
        compressed_chars=len(compressed),
        raw_tokens=raw_tokens,
        compressed_tokens=compressed_tokens,
        savings_pct=savings,
    )


def apply_rtk_to_review_context_fields(
    git_diff: str,
    *,
    settings: Settings | None = None,
    repo_path: Path | str | None = None,
    base_ref: str | None = None,
) -> tuple[str, str, DiffCompressResult]:
    """Return (prompt_diff, scanner_diff, stats)."""
    result = compress_diff_for_review(
        git_diff,
        settings=settings,
        repo_path=repo_path,
        base_ref=base_ref,
    )
    return result.compressed, result.raw, result
