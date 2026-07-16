"""Local Cursor Bridge — runs Cursor SDK against GitLab-connected clone, then git push."""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Cursor Bridge", version="0.1.0")


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
    match = re.search(r"\{{[\s\S]*\}}", text)
    if match:
        return json.loads(match.group())
    return {}


def _run_cursor_prompt(prompt: str, repo: Path, model: str) -> str:
    api_key = os.environ.get("CURSOR_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="CURSOR_API_KEY not set. Add it from Cursor Settings → API.",
        )
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
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


def _llm_fallback(prompt: str) -> str:
    """Fallback when cursor-sdk unavailable — uses OpenAI-compatible API from env."""
    import httpx

    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("CODING_MODEL", "gpt-4o-mini")
    if not api_key:
        return '{"approved": false, "summary": "No LLM configured", "findings": [], "suggestions": []}'
    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        },
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


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
        "cursor_sdk": has_sdk,
        "repo_path": repo,
        "has_api_key": bool(os.environ.get("CURSOR_API_KEY")),
    }


@app.post("/develop")
async def develop(request: DevelopRequest):
    repo = _resolve_repo(request.repo_path)
    _checkout_branch(repo, request.branch_name)

    try:
        content = _run_cursor_prompt(request.prompt, repo, request.model)
    except HTTPException:
        content = _llm_fallback(request.prompt)

    files = _parse_json_object(content)
    if files and all(isinstance(v, str) for v in files.values()):
        for rel_path, body in files.items():
            target = repo / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")

    if files:
        _git(["add", "-A"], repo)
        _git(["commit", "-m", f"feat({request.task_key}): Cursor develop"], repo)
        _git(["push", "origin", request.branch_name], repo)

    return {
        "git_pushed": True,
        "files": files,
        "summary": f"Cursor develop on {request.branch_name} — pushed to GitLab",
        "run_id": request.run_id,
    }


@app.post("/review")
async def review(request: ReviewRequest):
    repo = _resolve_repo(request.repo_path)
    if request.branch_name:
        try:
            _checkout_branch(repo, request.branch_name)
        except HTTPException:
            pass

    try:
        content = _run_cursor_prompt(request.prompt, repo, request.model)
    except HTTPException:
        content = _llm_fallback(request.prompt)

    review_data = _parse_json_object(content)
    if not review_data:
        review_data = {
            "approved": False,
            "summary": content[:500] or "Empty review response",
            "findings": [],
            "suggestions": [],
        }
    return {"review": review_data, "run_id": request.run_id}
