"""Local Cursor Bridge — develop via 9Router/SDK; review via Cursor CLI agent."""

import asyncio
import json
import os
import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.config import get_settings
from core.tracing import GenerationTimer, flush_tracing, init_tracing, record_generation, tracing_status
from shared.cursor_cli.fallback import should_fallback_from_cursor_cli
from shared.cursor_cli.models import ReviewContext
from shared.cursor_cli.models import ReviewRequest as CursorCliReviewRequest
from shared.cursor_cli.response_parser import parse_review_response
from shared.cursor_cli.runner import CursorCliError, resolve_cursor_cli_bin, run_cursor_review_request
from shared.cursor_cli.model_utils import normalize_cursor_cli_model

_DEFAULT_9ROUTER_MODEL = "cu/claude-4.5-sonnet"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_tracing()
    try:
        yield
    finally:
        flush_tracing()


app = FastAPI(title="Cursor Bridge", version="0.3.0", lifespan=_lifespan)


class DevelopRequest(BaseModel):
    run_id: str
    task_key: str
    branch_name: str
    prompt: str
    repo_path: str = ""
    model: str = "composer-2.5"


class ReviewRequest(BaseModel):
    run_id: str
    task_key: str
    branch_name: str
    repo_path: str = ""
    context: ReviewContext
    model: str | None = None
    workspace: str | None = None
    output_format: str | None = None
    mode: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=1800)


def _resolve_repo(path: str) -> Path:
    repo = Path(path or os.environ.get("CURSOR_REPO_PATH", "")).expanduser()
    if not repo.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Repo path not found: {repo}. Set CURSOR_REPO_PATH in .env",
        )
    return repo


def _git(cmd: list[str], repo: Path) -> str:
    result = subprocess.run(
        ["git", *cmd],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"git {' '.join(cmd)} failed: {result.stderr or result.stdout}",
        )
    return result.stdout.strip()


def _checkout_branch(repo: Path, branch_name: str) -> None:
    _git(["fetch", "origin"], repo)
    branches = _git(["branch", "--list"], repo)
    if branch_name in branches or f"* {branch_name}" in branches:
        _git(["checkout", branch_name], repo)
    else:
        _git(["checkout", "-B", branch_name, f"origin/{branch_name}"], repo)
    _git(["pull", "origin", branch_name], repo)


def _parse_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        return json.loads(match.group())
    return {}


def _uses_9router() -> bool:
    base = (os.environ.get("LLM_BASE_URL") or "").lower()
    return "20128" in base or "9router" in base or "127.0.0.1" in base or "localhost" in base


def _develop_model(requested: str | None = None) -> str:
    model = (
        (requested or "").strip()
        or os.environ.get("CODING_MODEL", "").strip()
        or os.environ.get("LLM_MODEL", "").strip()
        or _DEFAULT_9ROUTER_MODEL
    )
    provider_prefixes = ("oc/", "cu/", "cc/", "ag/", "cx/", "gh/", "kr/")
    if _uses_9router() and not model.startswith(provider_prefixes):
        if model in {"composer-2.5", "composer-2", "auto"} or model.startswith("gpt-"):
            return os.environ.get(
                "CODING_MODEL",
                os.environ.get("NINEROUTER_CURSOR_MODEL", _DEFAULT_9ROUTER_MODEL),
            )
    return model


def _review_model(requested: str | None = None) -> str:
    settings = get_settings()
    raw = (
        (requested or "").strip()
        or settings.code_review_model.strip()
        or settings.cursor_model.strip()
    )
    return normalize_cursor_cli_model(raw)


def _run_cursor_sdk(prompt: str, repo: Path, model: str) -> str:
    api_key = os.environ.get("CURSOR_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="CURSOR_API_KEY not set. Add it from Cursor Settings → API.",
        )
    try:
        from cursor_sdk import Agent, LocalAgentOptions
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Install cursor-sdk: pip install cursor-sdk",
        ) from exc

    with Agent.create(
        model=model,
        api_key=api_key,
        local=LocalAgentOptions(cwd=str(repo)),
    ) as agent:
        run = agent.send(prompt)
        for message in run.messages():
            if message.type == "assistant":
                for block in message.message.content:
                    if block.type == "text":
                        return block.text
        run.wait()
    return ""


def _parse_chat_completion_body(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response body")

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    data, _end = decoder.raw_decode(text)
    if isinstance(data, dict):
        return data
    raise ValueError(f"expected JSON object, got {type(data).__name__}")


def _content_from_message(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        joined = "".join(parts).strip()
        if joined:
            return joined
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    return ""


def _content_from_completion(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message")
    if isinstance(message, dict):
        text = _content_from_message(message)
        if text:
            return text
    delta = choice.get("delta")
    if isinstance(delta, dict):
        return _content_from_message(delta)
    text = choice.get("text")
    return text if isinstance(text, str) else ""


def _content_from_sse(text: str) -> str:
    chunks: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        piece = _content_from_completion(event)
        if piece:
            chunks.append(piece)
    return "".join(chunks)


def _extract_9router_content(response_text: str) -> str:
    text = (response_text or "").strip()
    if not text:
        raise ValueError("empty response body")

    if text.startswith("data:"):
        content = _content_from_sse(text)
        if content:
            return content
        raise ValueError("SSE response contained no assistant content")

    data = _parse_chat_completion_body(text)
    content = _content_from_completion(data)
    if content:
        return content

    sse_content = _content_from_sse(text)
    if sse_content:
        return sse_content
    raise ValueError("completion contained no assistant content")


def _9router_review_model() -> str:
    """Model for 9Router review fallback (provider-prefixed IDs)."""
    return _9router_review_model_candidates()[0]


def _9router_review_model_candidates() -> list[str]:
    provider_prefixes = ("oc/", "cu/", "cc/", "ag/", "cx/", "gh/", "kr/")
    seen: set[str] = set()
    candidates: list[str] = []
    for raw in (
        os.environ.get("NINEROUTER_REVIEW_MODEL", "").strip(),
        os.environ.get("NINEROUTER_CURSOR_MODEL", "").strip(),
        os.environ.get("CODE_REVIEW_MODEL", "").strip(),
        _DEFAULT_9ROUTER_MODEL,
        "cu/claude-4-sonnet",
    ):
        if not raw:
            continue
        model = raw
        if _uses_9router() and not model.startswith(provider_prefixes):
            if model in {"composer-2.5", "composer-2", "auto"} or model.startswith("gpt-"):
                model = _DEFAULT_9ROUTER_MODEL
        if model not in seen:
            seen.add(model)
            candidates.append(model)
    return candidates or [_DEFAULT_9ROUTER_MODEL]


def _resolve_9router_model(model: str | None, *, for_review: bool = False) -> str:
    if for_review:
        explicit = (model or "").strip()
        provider_prefixes = ("oc/", "cu/", "cc/", "ag/", "cx/", "gh/", "kr/")
        if explicit.startswith(provider_prefixes):
            return explicit
        return _9router_review_model()
    return _develop_model(model)


def _llm_via_9router(prompt: str, model: str | None = None, *, for_review: bool = False) -> str:
    import httpx

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:20128/v1")
    models_to_try = (
        _9router_review_model_candidates()
        if for_review
        else [_resolve_9router_model(model, for_review=False)]
    )
    if for_review and model:
        preferred = _resolve_9router_model(model, for_review=True)
        if preferred not in models_to_try:
            models_to_try = [preferred, *models_to_try]
        else:
            models_to_try = [preferred] + [m for m in models_to_try if m != preferred]

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_detail = "no models attempted"
    for use_model in models_to_try:
        try:
            response = httpx.post(
                url,
                headers=headers,
                json={
                    "model": use_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 8192,
                    "stream": False,
                },
                timeout=300.0,
            )
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"9Router not reachable at {base_url}. "
                    "Start 9Router and open http://127.0.0.1:20128/dashboard"
                ),
            ) from exc

        if response.status_code >= 400:
            detail = response.text[:800]
            hint = (
                "Set LLM_API_KEY to a key from 9Router Dashboard → Keys "
                "(requireApiKey is enabled)."
                if response.status_code == 401
                else f"Use a 9Router model like {_DEFAULT_9ROUTER_MODEL} "
                "(see Dashboard → Providers / GET /v1/models)."
            )
            last_detail = (
                f"9Router error {response.status_code} for model '{use_model}': {detail}. {hint}"
            )
            continue

        try:
            return _extract_9router_content(response.text)
        except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError) as exc:
            last_detail = (
                f"Model '{use_model}' returned empty/invalid content "
                f"({exc}). Body: {response.text[:400]}"
            )
            continue

    raise HTTPException(
        status_code=502,
        detail=(
            f"9Router returned no assistant content after trying {models_to_try}. "
            f"{last_detail}. Prompt size: {len(prompt)} chars."
        ),
    )


def _run_develop_prompt(prompt: str, repo: Path, model: str) -> str:
    if _uses_9router() or not os.environ.get("CURSOR_API_KEY"):
        return _llm_via_9router(prompt, model)

    try:
        return _run_cursor_sdk(prompt, repo, model)
    except HTTPException:
        return _llm_via_9router(prompt, model)


def _run_cursor_cli_review(
    request: ReviewRequest,
) -> tuple[str, CursorCliReviewRequest, Any, str]:
    """Run review via Cursor CLI; optional 9Router fallback when CLI unavailable."""
    from shared.cursor_cli.prompt_builder import build_review_prompt

    settings = get_settings()
    workspace = (request.workspace or "").strip() or None
    if settings.cursor_cli_review_use_workspace and not workspace:
        workspace = (settings.cursor_repo_path or "").strip() or None
    cli_request = CursorCliReviewRequest(
        context=request.context,
        model=request.model,
        workspace=workspace,
        output_format=request.output_format or settings.cursor_cli_output_format,
        mode=request.mode or settings.cursor_cli_review_mode or settings.cursor_cli_mode,
        timeout_seconds=request.timeout_seconds or settings.cursor_cli_timeout_seconds,
    )
    prompt = build_review_prompt(
        request.context,
        output_format=cli_request.output_format or settings.cursor_cli_output_format,
    )

    try:
        result = run_cursor_review_request(cli_request, settings=settings)
    except CursorCliError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    failure_text = f"{result.stderr}\n{result.stdout}".strip()
    if (
        settings.cursor_review_fallback_9router
        and _uses_9router()
        and should_fallback_from_cursor_cli(result.stderr, result.stdout)
    ):
        try:
            content = _llm_via_9router(
                prompt,
                _9router_review_model(),
                for_review=True,
            )
        except HTTPException as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=(
                    "Cursor CLI review failed and 9Router fallback also failed. "
                    f"CLI: {failure_text[:350]}. 9Router: {exc.detail}"
                ),
            ) from exc
        return content, cli_request, result, "9router-fallback"

    if result.timed_out:
        raise HTTPException(
            status_code=504,
            detail=f"Cursor CLI review timed out after {cli_request.timeout_seconds}s",
        )
    if result.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Cursor CLI exited with code {result.returncode}: "
                f"{failure_text[:800]}"
            ),
        )
    if not result.stdout.strip():
        raise HTTPException(
            status_code=502,
            detail=f"Cursor CLI returned empty stdout. {failure_text[:400]}",
        )
    return result.stdout, cli_request, result, "cursor-cli"


def _as_lines(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                lines.append(item.strip())
            continue
        if isinstance(item, dict):
            severity = str(item.get("severity") or "").strip().upper()
            path = str(item.get("file") or item.get("path") or "").strip()
            msg = str(
                item.get("message")
                or item.get("description")
                or item.get("suggestion")
                or item.get("text")
                or ""
            ).strip()
            parts = []
            if severity:
                parts.append(f"[{severity}]")
            if path:
                parts.append(path)
            if msg:
                parts.append(("- " if parts else "") + msg)
            line = " ".join(parts).strip()
            if line:
                lines.append(line)
    return lines


@app.get("/health")
async def health():
    repo = os.environ.get("CURSOR_REPO_PATH", "")
    has_sdk = False
    try:
        import cursor_sdk  # noqa: F401

        has_sdk = True
    except ImportError:
        pass

    cli_path = None
    cli_error = None
    try:
        cli_path = resolve_cursor_cli_bin(get_settings().cursor_cli_bin)
    except CursorCliError as exc:
        cli_error = str(exc)

    settings = get_settings()
    return {
        "status": "ok",
        "mode": "cursor-cli",
        "review_fallback_9router": settings.cursor_review_fallback_9router,
        "develop_mode": "9router" if _uses_9router() or not os.environ.get("CURSOR_API_KEY") else "cursor-sdk",
        "review_model": _review_model(),
        "cursor_cli_bin": cli_path,
        "cursor_cli_error": cli_error,
        "llm_base_url": os.environ.get("LLM_BASE_URL", ""),
        "cursor_sdk": has_sdk,
        "repo_path": repo,
        "has_cursor_api_key": bool(os.environ.get("CURSOR_API_KEY")),
        "tracing": tracing_status(),
    }


@app.get("/cli-info")
async def cli_info():
    settings = get_settings()
    try:
        resolved = resolve_cursor_cli_bin(settings.cursor_cli_bin)
    except CursorCliError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "cursor_cli_bin": resolved,
        "review_model": _review_model(),
        "output_format": settings.cursor_cli_output_format,
        "mode": settings.cursor_cli_mode,
        "timeout_seconds": settings.cursor_cli_timeout_seconds,
    }


@app.post("/develop")
async def develop(request: DevelopRequest):
    repo = _resolve_repo(request.repo_path)
    await asyncio.to_thread(_checkout_branch, repo, request.branch_name)
    with GenerationTimer() as timer:
        content = await asyncio.to_thread(_run_develop_prompt, request.prompt, repo, request.model)
    record_generation(
        run_id=request.run_id,
        name="cursor_develop",
        model=_develop_model(request.model),
        prompt=request.prompt,
        output=content,
        latency_ms=timer.elapsed_ms,
        tags=["cursor_bridge", "develop"],
    )

    files = _parse_json_object(content)
    if files and all(isinstance(v, str) for v in files.values()):
        for rel_path, body in files.items():
            target = repo / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    if files:
        await asyncio.to_thread(_git, ["add", "-A"], repo)
        await asyncio.to_thread(
            _git,
            ["commit", "-m", f"feat({request.task_key}): Cursor develop"],
            repo,
        )
        await asyncio.to_thread(_git, ["push", "origin", request.branch_name], repo)

    return {
        "git_pushed": True,
        "files": files,
        "summary": f"Cursor develop on {request.branch_name} — pushed to GitLab",
        "run_id": request.run_id,
        "model": _develop_model(request.model),
    }


@app.post("/review")
async def review(request: ReviewRequest):
    with GenerationTimer() as timer:
        content, cli_request, cli_result, backend = await asyncio.to_thread(
            _run_cursor_cli_review, request
        )

    from shared.cursor_cli.prompt_builder import build_review_prompt

    prompt = build_review_prompt(
        request.context,
        output_format=cli_request.output_format or get_settings().cursor_cli_output_format,
    )
    review_model = (
        _9router_review_model()
        if backend == "9router-fallback"
        else _review_model(cli_request.model)
    )
    record_generation(
        run_id=request.run_id,
        name="cursor_review",
        model=review_model,
        prompt=prompt,
        output=content,
        latency_ms=timer.elapsed_ms,
        tags=["cursor_bridge", "review", backend.replace("-", "_")],
    )

    review_data = parse_review_response(content)

    review_data["findings"] = _as_lines(review_data.get("findings"))
    review_data["suggestions"] = _as_lines(review_data.get("suggestions"))
    return {
        "review": review_data,
        "run_id": request.run_id,
        "model": review_model,
        "backend": backend,
        "raw_content": content[:4000],
        "prompt_chars": cli_result.prompt_chars,
    }
