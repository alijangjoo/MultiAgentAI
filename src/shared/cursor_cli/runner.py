import glob
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings, get_settings
from shared.cursor_cli.model_utils import normalize_cursor_cli_model
from shared.cursor_cli.models import CursorCliResult, ReviewContext, ReviewRequest
from shared.cursor_cli.prompt_builder import build_review_prompt
from shared.cursor_cli.response_parser import is_incomplete_review_response, parse_review_response


class CursorCliError(Exception):
    """Raised when the Cursor CLI cannot be started."""


@dataclass
class _CliRunResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    prompt_chars: int
    timed_out: bool = False


# Windows CreateProcess command-line limit (~8191 chars).
_WINDOWS_CMDLINE_LIMIT = 8191
_WINDOWS_ARGV_PROMPT_LIMIT = 3500


def _cursor_agent_worker_globs() -> list[str]:
    patterns: list[str] = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        base = os.path.join(
            appdata,
            "Cursor",
            "User",
            "globalStorage",
            "anysphere.cursor-agent-worker",
            "agent-cli",
            ".local",
            "share",
            "cursor-agent",
            "versions",
        )
        patterns.extend(
            [
                os.path.join(base, "*", "cursor-agent.cmd"),
                os.path.join(base, "*", "cursor-agent.exe"),
                os.path.join(base, "*", "agent.cmd"),
                os.path.join(base, "*", "agent.exe"),
            ]
        )

    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
    patterns.extend(
        [
            os.path.join(local_bin, "agent.exe"),
            os.path.join(local_bin, "agent.cmd"),
            os.path.join(local_bin, "cursor-agent.exe"),
            os.path.join(local_bin, "cursor-agent.cmd"),
        ]
    )
    return patterns


def _official_windows_install_candidates() -> list[str]:
    local_app = os.environ.get("LOCALAPPDATA", "")
    if not local_app:
        return []
    base = os.path.join(local_app, "cursor-agent")
    return [
        os.path.join(base, "agent.cmd"),
        os.path.join(base, "agent.exe"),
        os.path.join(base, "cursor-agent.cmd"),
        os.path.join(base, "cursor-agent.exe"),
    ]


def _discover_cursor_cli() -> str | None:
    for name in ("agent", "cursor-agent"):
        resolved = shutil.which(name)
        if resolved:
            return resolved

    for path in _official_windows_install_candidates():
        if os.path.isfile(path):
            return path

    candidates: list[str] = []
    for pattern in _cursor_agent_worker_globs():
        candidates.extend(glob.glob(pattern))

    if not candidates:
        return None

    def _sort_key(path: str) -> tuple[float, str]:
        version_dir = Path(path).parent.name
        try:
            return (float(version_dir.split("-", 1)[0].replace(".", "")), path)
        except ValueError:
            return (0.0, path)

    return sorted(set(candidates), key=_sort_key, reverse=True)[0]


def resolve_cursor_cli_bin(cli_bin: str | None = None) -> str:
    """Resolve Cursor CLI binary from name, PATH, or known install locations."""
    name = (cli_bin or "agent").strip() or "agent"
    if os.path.isabs(name) and os.path.isfile(name):
        return name

    resolved = shutil.which(name)
    if resolved:
        return resolved

    if name in {"agent", "cursor-agent"}:
        discovered = _discover_cursor_cli()
        if discovered:
            return discovered

    raise CursorCliError(
        f"Cursor CLI binary '{name}' not found on PATH. "
        "Install with: irm 'https://cursor.com/install?win32=true' | iex "
        "then verify: agent --version "
        "or set CURSOR_CLI_BIN to the full path of cursor-agent.cmd"
    )


def _resolve_review_model(settings: Settings, model: str | None) -> str | None:
    """Match CursorReviewAgent: request override → cursor_model → code_review_model."""
    raw = (model or settings.cursor_model or settings.code_review_model or "").strip()
    normalized = normalize_cursor_cli_model(raw or None)
    return normalized or None


def _resolve_output_format(settings: Settings, output_format: str | None) -> str:
    return (output_format or settings.cursor_cli_output_format).strip() or "text"


def _resolve_workspace(settings: Settings, workspace: str | None) -> str | None:
    if not settings.cursor_cli_review_use_workspace:
        return (workspace or "").strip() or None
    chosen = (workspace or settings.cursor_repo_path or "").strip()
    return chosen or None


def _max_prompt_chars(base_cmd: list[str]) -> int:
    base_len = len(subprocess.list2cmdline(base_cmd)) + 64
    if os.name != "nt":
        return 120_000
    return max(1200, min(_WINDOWS_ARGV_PROMPT_LIMIT, _WINDOWS_CMDLINE_LIMIT - base_len))


def _estimate_cmdline_length(cmd: list[str], prompt: str) -> int:
    return len(subprocess.list2cmdline([*cmd, prompt]))


def _prompt_fits_argv(cmd: list[str], prompt: str) -> bool:
    if os.name != "nt":
        return True
    return _estimate_cmdline_length(cmd, prompt) <= _WINDOWS_CMDLINE_LIMIT - 32


def _build_command_base(
    *,
    cli_bin: str,
    settings: Settings,
    model: str | None,
    workspace: str | None,
    output_format: str | None,
    mode: str | None,
) -> list[str]:
    fmt = _resolve_output_format(settings, output_format)
    agent_mode = (mode or settings.cursor_cli_mode).strip() or "ask"
    chosen_model = _resolve_review_model(settings, model)
    chosen_workspace = _resolve_workspace(settings, workspace)

    cmd = [
        cli_bin,
        "-p",
        "--trust",
        "--approve-mcps",
        "--output-format",
        fmt,
    ]

    if agent_mode and agent_mode != "agent":
        cmd.extend(["--mode", agent_mode])

    if chosen_model:
        cmd.extend(["--model", chosen_model])

    if chosen_workspace:
        cmd.extend(["--workspace", chosen_workspace])

    return cmd


def _build_command(
    *,
    cli_bin: str,
    prompt: str,
    settings: Settings,
    model: str | None,
    workspace: str | None,
    output_format: str | None,
    mode: str | None,
) -> list[str]:
    return [
        *_build_command_base(
            cli_bin=cli_bin,
            settings=settings,
            model=model,
            workspace=workspace,
            output_format=output_format,
            mode=mode,
        ),
        prompt,
    ]


def _redact_prompt(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    redacted = list(cmd)
    redacted[-1] = f"<prompt:{len(cmd[-1])} chars>"
    return redacted


def _build_env(settings: Settings) -> dict[str, str]:
    env = os.environ.copy()
    if settings.cursor_api_key:
        env["CURSOR_API_KEY"] = settings.cursor_api_key
    if settings.http_proxy:
        env["HTTP_PROXY"] = settings.http_proxy
        env["http_proxy"] = settings.http_proxy
    if settings.https_proxy:
        env["HTTPS_PROXY"] = settings.https_proxy
        env["https_proxy"] = settings.https_proxy
    if settings.no_proxy:
        env["NO_PROXY"] = settings.no_proxy
        env["no_proxy"] = settings.no_proxy
    return env


def _run_subprocess(cmd: list[str], *, env: dict[str, str], timeout: int) -> _CliRunResult:
    prompt = cmd[-1] if cmd else ""
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (
            (exc.stdout or b"").decode("utf-8", errors="replace")
        )
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (
            (exc.stderr or b"").decode("utf-8", errors="replace")
        )
        return _CliRunResult(
            returncode=-1,
            stdout=stdout,
            stderr=stderr or f"Cursor CLI timed out after {timeout}s",
            command=_redact_prompt(cmd),
            prompt_chars=len(prompt),
            timed_out=True,
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) == 206:
            raise CursorCliError(
                "Prompt too long for Windows command line; retry with file delivery."
            ) from exc
        raise

    return _CliRunResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        command=_redact_prompt(cmd),
        prompt_chars=len(prompt),
        timed_out=False,
    )


def _trim_context_for_prompt(
    context: ReviewContext,
    *,
    output_format: str,
    max_prompt_chars: int,
) -> str:
    note = (
        "\n\n[... git diff truncated to fit Windows CLI limits; "
        "review the shown hunks ...]\n\n"
    )
    diff = context.git_diff

    attempts: list[ReviewContext] = [context]
    if len(diff) > 500:
        for budget in (len(diff), len(diff) // 2, len(diff) // 4, 6000, 4000, 2500, 1500):
            head = max(400, budget // 2)
            tail = max(400, budget - head)
            attempts.append(
                ReviewContext(
                    **{
                        **context.model_dump(),
                        "git_diff": diff[:head] + note + diff[-tail:],
                    }
                )
            )
    attempts.append(
        ReviewContext(
            title=context.title,
            description=None,
            git_diff=diff[:800] + note + diff[-600:],
            specs=None,
            review_rules=None,
            extra_context={"jira_ticket": (context.extra_context or {}).get("jira_ticket")}
            if context.extra_context
            else None,
            language=context.language,
        )
    )

    best = attempts[-1]
    for candidate in attempts:
        prompt = build_review_prompt(candidate, output_format=output_format)
        if len(prompt) <= max_prompt_chars:
            return prompt
        best = candidate

    prompt = build_review_prompt(best, output_format=output_format)
    if len(prompt) <= max_prompt_chars:
        return prompt
    return prompt[: max_prompt_chars - 20] + "\n[truncated]"


def _truncate_diff_for_argv(
    context: ReviewContext,
    *,
    base_cmd: list[str],
    output_format: str,
) -> str:
    """Shrink prompt until argv fits Windows CreateProcess limits."""
    max_chars = _max_prompt_chars(base_cmd)
    prompt = build_review_prompt(context, output_format=output_format)
    if _prompt_fits_argv(base_cmd, prompt):
        return prompt
    return _trim_context_for_prompt(
        context,
        output_format=output_format,
        max_prompt_chars=max_chars,
    )


def _model_attempts(settings: Settings, model: str | None) -> list[str | None]:
    primary = _resolve_review_model(settings, model)
    attempts: list[str | None] = []
    if primary:
        attempts.append(primary)
    if primary != "auto":
        attempts.append("auto")
    attempts.append(None)
    return attempts


def _resolve_review_mode(settings: Settings, mode: str | None) -> str:
    return (mode or settings.cursor_cli_review_mode or settings.cursor_cli_mode).strip() or "agent"


def _is_placeholder_stdout(stdout: str) -> bool:
    text = (stdout or "").strip()
    if not text:
        return False
    parsed = parse_review_response(text)
    return is_incomplete_review_response(text, parsed)


def _cli_failure_text(result: _CliRunResult) -> str:
    return (result.stderr or result.stdout or "").strip()


def _review_attempt_plans(
    settings: Settings,
    mode: str | None,
    output_format: str | None,
) -> list[tuple[str | None, str | None]]:
    """Mode/format attempts: configured first, then agent+json retry on placeholder."""
    resolved_mode = _resolve_review_mode(settings, mode)
    resolved_fmt = _resolve_output_format(settings, output_format)
    plans: list[tuple[str | None, str | None]] = [(resolved_mode, output_format)]
    if resolved_mode != "agent":
        plans.append(("agent", output_format))
    if resolved_fmt != "json":
        plans.append(("agent", "json"))
    # Deduplicate while preserving order
    seen: set[tuple[str | None, str | None]] = set()
    unique: list[tuple[str | None, str | None]] = []
    for plan in plans:
        if plan not in seen:
            seen.add(plan)
            unique.append(plan)
    return unique


def _execute_review(
    *,
    context: ReviewContext,
    settings: Settings,
    model: str | None,
    workspace: str | None,
    output_format: str | None,
    mode: str | None,
    timeout_seconds: int | None,
) -> CursorCliResult:
    """Core runner — ported from CursorReviewAgent with argv embedding + model retry."""
    cli_bin = resolve_cursor_cli_bin(settings.cursor_cli_bin)
    timeout = timeout_seconds or settings.cursor_cli_timeout_seconds
    env = _build_env(settings)

    last_result: _CliRunResult | None = None
    last_prompt = ""
    attempt_plans = _review_attempt_plans(settings, mode, output_format)

    for attempt_model in _model_attempts(settings, model):
        review_workspace = workspace if settings.cursor_cli_review_use_workspace else None
        for attempt_mode, attempt_fmt in attempt_plans:
            base_cmd = _build_command_base(
                cli_bin=cli_bin,
                settings=settings,
                model=attempt_model,
                workspace=review_workspace,
                output_format=attempt_fmt,
                mode=attempt_mode,
            )
            fmt = _resolve_output_format(settings, attempt_fmt)
            prompt = _truncate_diff_for_argv(context, base_cmd=base_cmd, output_format=fmt)
            last_prompt = prompt
            if not _prompt_fits_argv(base_cmd, prompt):
                prompt = _trim_context_for_prompt(
                    context,
                    output_format=fmt,
                    max_prompt_chars=_max_prompt_chars(base_cmd),
                )
                last_prompt = prompt
            cmd = [*base_cmd, prompt]
            result = _run_subprocess(cmd, env=env, timeout=timeout)
            last_result = result
            if result.returncode == 0 and (result.stdout or "").strip():
                if not _is_placeholder_stdout(result.stdout):
                    return CursorCliResult(
                        returncode=result.returncode,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        command=result.command,
                        prompt_chars=len(prompt),
                        timed_out=result.timed_out,
                    )
                continue
            if "too long" in _cli_failure_text(result).lower():
                context = ReviewContext(
                    **{
                        **context.model_dump(),
                        "git_diff": context.git_diff[:2000]
                        + "\n[truncated]\n"
                        + context.git_diff[-1000:],
                        "specs": None,
                        "review_rules": None,
                        "extra_context": None,
                    }
                )
                break

    assert last_result is not None
    return CursorCliResult(
        returncode=last_result.returncode,
        stdout=last_result.stdout,
        stderr=last_result.stderr,
        command=last_result.command,
        prompt_chars=len(last_prompt),
        timed_out=last_result.timed_out,
    )


def run_cursor_review(
    context: ReviewContext,
    settings: Settings | None = None,
    *,
    model: str | None = None,
    workspace: str | None = None,
    output_format: str | None = None,
    mode: str | None = None,
    timeout_seconds: int | None = None,
) -> CursorCliResult:
    """Run Cursor Agent via subprocess — same contract as CursorReviewAgent."""
    cfg = settings or get_settings()
    return _execute_review(
        context=context,
        settings=cfg,
        model=model,
        workspace=workspace,
        output_format=output_format,
        mode=mode,
        timeout_seconds=timeout_seconds,
    )


def run_cursor_review_request(
    request: ReviewRequest,
    settings: Settings | None = None,
) -> CursorCliResult:
    """Run review from a ReviewRequest wrapper (AgentFramework integration)."""
    cfg = settings or get_settings()
    return _execute_review(
        context=request.context,
        settings=cfg,
        model=request.model,
        workspace=request.workspace,
        output_format=request.output_format,
        mode=request.mode,
        timeout_seconds=request.timeout_seconds,
    )
