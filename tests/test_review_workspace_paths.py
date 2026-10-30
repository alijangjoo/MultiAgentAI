from pathlib import Path

import pytest

from shared.cursor_cli.review_workspace import (
    _summarize_git_failure_output,
    _worktree_root,
)


def test_summarize_git_failure_truncates_progress_spam() -> None:
    raw = "Updating files: 99%\n" * 50 + "fatal: index reset failed"
    out = _summarize_git_failure_output(raw)
    assert "Updating files" not in out
    assert "fatal:" in out


def test_summarize_git_failure_long_path_hint() -> None:
    raw = "error: unable to create file foo.cs: Filename too long\nfatal: done"
    out = _summarize_git_failure_output(raw)
    assert "Filename too long" in out
    assert "CURSOR_REVIEW_WORKTREE_ROOT" in out


def test_worktree_root_honors_explicit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "shared.cursor_cli.review_workspace.get_settings",
        lambda: type("S", (), {"cursor_review_worktree_root": r"D:\wt"})(),
    )
    root = _worktree_root(Path(r"C:\long\clone\dizi"))
    assert root == Path(r"D:\wt").resolve()


def test_worktree_root_windows_default_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shared.cursor_cli.review_workspace.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    monkeypatch.setattr(
        "shared.cursor_cli.review_workspace.get_settings",
        lambda: type("S", (), {"cursor_review_worktree_root": ""})(),
    )
    root = _worktree_root(Path(r"C:\Users\me\source\repos\dizi_v2\dizi"))
    assert root == Path(r"C:\Users\me\AppData\Local\af\wt").resolve()
