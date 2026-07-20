"""Local Cursor Bridge — prefers 9Router (e.g. OpenCode Free) for review/develop."""

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Cursor Bridge", version="0.2.0")


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
    mr_title: str
    prompt: str
    mr_changes: list[dict] = Field(default_factory=list)
    repo_path: str = ""
    model: str = "composer-2.5"


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


def _review_model(requested: str | None = None) -> str:
    """Prefer CODE_REVIEW_MODEL / LLM_MODEL; keep 9Router provider-prefixed IDs as-is."""
    model = (
        (requested or "").strip()
        or os.environ.get("CODE_REVIEW_MODEL", "").strip()
        or os.environ.get("CODING_MODEL", "").strip()
        or os.environ.get("LLM_MODEL", "").strip()
        or "oc/deepseek-v4-flash-free"
    )
    # Generic OpenAI-style names are not registered on 9Router → remap to configured default
    provider_prefixes = ("oc/", "cu/", "cc/", "ag/", "cx/", "gh/", "kr/")
    if _uses_9router() and not model.startswith(provider_prefixes):
        if model in {"composer-2.5", "composer-2", "auto"} or model.startswith("gpt-"):
            return os.environ.get(
                "CODE_REVIEW_MODEL",
                os.environ.get("NINEROUTER_CURSOR_MODEL", "oc/deepseek-v4-flash-free"),
            )
    return model


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
    """Parse 9Router chat.completion body; tolerate trailing SSE junk like 'data: [DONE]'."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response body")

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Some 9Router providers append SSE trailers after a JSON object.
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
    """Assemble assistant text from OpenAI-style SSE (used when OpenCode forces stream)."""
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

    # Hybrid body: JSON object + trailing SSE chunks
    sse_content = _content_from_sse(text)
    if sse_content:
        return sse_content
    raise ValueError("completion contained no assistant content")


def _llm_via_9router(prompt: str, model: str | None = None) -> str:
    """Call 9Router OpenAI-compatible API (e.g. OpenCode Free oc/* models)."""
    import httpx

    api_key = os.environ.get("LLM_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:20128/v1")
    use_model = _review_model(model)
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx.post(
            url,
            headers=headers,
            json={
                "model": use_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
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
            else "Use an OpenCode Free model like oc/deepseek-v4-flash-free "
            "(see Dashboard → Providers / GET /v1/models)."
        )
        raise HTTPException(
            status_code=502,
            detail=(
                f"9Router error {response.status_code} for model '{use_model}': {detail}. "
                f"{hint}"
            ),
        )
    try:
        return _extract_9router_content(response.text)
    except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unexpected 9Router response: {response.text[:400]}",
        ) from exc


def _run_prompt(prompt: str, repo: Path, model: str) -> str:
    """
    Preferred path for this project: 9Router → OpenCode Free (oc/*).
    Optional fallback: Cursor SDK when CURSOR_API_KEY is set and 9Router is not used.
    """
    if _uses_9router() or not os.environ.get("CURSOR_API_KEY"):
        return _llm_via_9router(prompt, model)

    try:
        return _run_cursor_sdk(prompt, repo, model)
    except HTTPException:
        return _llm_via_9router(prompt, model)


@app.get("/health")
async def health():
    repo = os.environ.get("CURSOR_REPO_PATH", "")
    has_sdk = False
    try:
        import cursor_sdk  # noqa: F401

        has_sdk = True
    except ImportError:
        pass
    return {
        "status": "ok",
        "mode": "9router" if _uses_9router() or not os.environ.get("CURSOR_API_KEY") else "cursor-sdk",
        "review_model": _review_model(),
        "llm_base_url": os.environ.get("LLM_BASE_URL", ""),
        "cursor_sdk": has_sdk,
        "repo_path": repo,
        "has_cursor_api_key": bool(os.environ.get("CURSOR_API_KEY")),
    }


@app.post("/develop")
async def develop(request: DevelopRequest):
    repo = _resolve_repo(request.repo_path)
    # Keep event loop free so /health stays responsive during long work.
    await asyncio.to_thread(_checkout_branch, repo, request.branch_name)
    content = await asyncio.to_thread(_run_prompt, request.prompt, repo, request.model)

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
        "model": _review_model(request.model),
    }


@app.post("/review")
async def review(request: ReviewRequest):
    repo = _resolve_repo(request.repo_path)
    if request.branch_name:
        try:
            await asyncio.to_thread(_checkout_branch, repo, request.branch_name)
        except HTTPException:
            pass

    content = await asyncio.to_thread(_run_prompt, request.prompt, repo, request.model)

    review_data = _parse_json_object(content)
    if not review_data:
        review_data = {
            "approved": False,
            "summary": content[:500] or "Empty review response",
            "findings": [],
            "suggestions": [],
        }

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

    review_data["findings"] = _as_lines(review_data.get("findings"))
    review_data["suggestions"] = _as_lines(review_data.get("suggestions"))
    return {
        "review": review_data,
        "run_id": request.run_id,
        "model": _review_model(request.model),
        "raw_content": content[:4000],
    }
