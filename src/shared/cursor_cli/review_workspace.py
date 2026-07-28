"""Ephemeral git worktree + Cursor skill materialization for MR reviews."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from core.config import get_settings
from shared.review.progress import ReviewProgressReporter
from slices.knowledge.review_docs import get_review_docs_service

SKILL_DIR_NAME = "sentinel-review"
SKILL_RELATIVE_PATH = Path(".cursor") / "skills" / SKILL_DIR_NAME / "SKILL.md"


class ReviewWorkspaceError(Exception):
    """Raised when a review workspace cannot be created or prepared."""


@dataclass(frozen=True)
class ReviewWorkspace:
    path: Path
    repo_path: Path
    branch_name: str
    skill_path: Path


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    settings = get_settings()
    timeout = timeout_seconds or settings.cursor_review_git_timeout_seconds
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReviewWorkspaceError(
            f"git {' '.join(args)} timed out after {timeout}s"
        ) from exc


def _git_output(args: list[str], *, cwd: Path) -> str:
    result = _run_git(args, cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ReviewWorkspaceError(f"git {' '.join(args)} failed: {detail}")
    return (result.stdout or "").strip()


def _worktree_root(repo_path: Path) -> Path:
    settings = get_settings()
    configured = (settings.cursor_review_worktree_root or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (repo_path.parent / ".agentframework-review-worktrees").resolve()


def materialize_review_skill(workspace: Path, skill_body: str) -> Path:
    skill_path = workspace / SKILL_RELATIVE_PATH
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(skill_body, encoding="utf-8")
    return skill_path


def _create_review_worktree_sync(
    *,
    repo_path: Path,
    branch_name: str,
    mr_iid: int,
    run_id: str,
    progress: ReviewProgressReporter | None = None,
) -> ReviewWorkspace:
    if not repo_path.is_dir():
        raise ReviewWorkspaceError(f"Repository path not found: {repo_path}")

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        raise ReviewWorkspaceError(f"Not a git repository: {repo_path}")

    branch = branch_name.strip()
    if not branch:
        raise ReviewWorkspaceError("MR source branch is required for review workspace")

    worktree_dir = _worktree_root(repo_path) / f"mr-{mr_iid}-{run_id[:8]}-{uuid.uuid4().hex[:6]}"
    if worktree_dir.exists():
        shutil.rmtree(worktree_dir, ignore_errors=True)

    if progress:
        progress.sync_log("git_fetch", f"git fetch origin {branch}")

    _git_output(["fetch", "origin", branch], cwd=repo_path)
    remote_ref = f"origin/{branch}"
    if progress:
        progress.sync_log("git_worktree", f"git worktree add --detach → {worktree_dir.name}")

    _git_output(
        ["worktree", "add", "--detach", str(worktree_dir), remote_ref],
        cwd=repo_path,
    )

    skill_body = get_review_docs_service().get_review_skill()["body"]
    if progress:
        progress.sync_log(
            "skill_write",
            f"Writing {SKILL_RELATIVE_PATH.as_posix()} from Knowledge Agent",
        )
    skill_path = materialize_review_skill(worktree_dir, skill_body)

    return ReviewWorkspace(
        path=worktree_dir,
        repo_path=repo_path,
        branch_name=branch,
        skill_path=skill_path,
    )


def _cleanup_review_worktree_sync(repo_path: Path, worktree_path: Path) -> None:
    if worktree_path.exists():
        result = _run_git(
            ["worktree", "remove", "--force", str(worktree_path)],
            cwd=repo_path,
            check=False,
        )
        if result.returncode != 0:
            shutil.rmtree(worktree_path, ignore_errors=True)
    _run_git(["worktree", "prune"], cwd=repo_path, check=False)


class ReviewWorkspaceSession:
    """Async context manager: git worktree at MR branch + sentinel-review skill."""

    def __init__(
        self,
        *,
        repo_path: str,
        branch_name: str,
        mr_iid: int,
        run_id: str,
        progress: ReviewProgressReporter | None = None,
    ) -> None:
        self._repo_path = Path(repo_path).expanduser().resolve()
        self._branch_name = branch_name
        self._mr_iid = mr_iid
        self._run_id = run_id
        self._progress = progress
        self._workspace: ReviewWorkspace | None = None

    async def __aenter__(self) -> ReviewWorkspace:
        if self._progress:
            self._progress.bind_loop(asyncio.get_running_loop())
        self._workspace = await asyncio.to_thread(
            _create_review_worktree_sync,
            repo_path=self._repo_path,
            branch_name=self._branch_name,
            mr_iid=self._mr_iid,
            run_id=self._run_id,
            progress=self._progress,
        )
        return self._workspace

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._workspace is None:
            return
        if self._progress:
            await self._progress.log("worktree_cleanup", "Removing ephemeral git worktree")
        await asyncio.to_thread(
            _cleanup_review_worktree_sync,
            self._workspace.repo_path,
            self._workspace.path,
        )
        self._workspace = None


def review_workspace_enabled() -> bool:
    settings = get_settings()
    return bool(settings.cursor_review_use_worktree and settings.cursor_repo_path.strip())
