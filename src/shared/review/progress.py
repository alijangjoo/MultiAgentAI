"""In-memory review progress events for live dashboard streaming (not persisted)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

EmitEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


class ReviewProgressReporter:
    """Emit short-lived step logs and CLI stdout/stderr to the Review dashboard via SSE."""

    def __init__(self, emit_event: EmitEvent | None = None) -> None:
        self._emit = emit_event
        self._loop: Any = None

    def bind_loop(self, loop: Any) -> None:
        self._loop = loop

    async def log(
        self,
        step: str,
        message: str,
        *,
        level: str = "info",
        **detail: Any,
    ) -> None:
        if not self._emit:
            return
        await self._emit(
            "step",
            {
                "step": step,
                "message": message,
                "level": level,
                "detail": detail,
                "at": datetime.now(UTC).isoformat(),
            },
        )

    async def cli_output(
        self,
        stream: str,
        text: str,
        *,
        final: bool = True,
        **detail: Any,
    ) -> None:
        """Stream Cursor CLI subprocess stdout/stderr to the dashboard."""
        if not self._emit or not (text or "").strip():
            return
        await self._emit(
            "cli_output",
            {
                "stream": stream,
                "text": text,
                "final": final,
                "detail": detail,
                "at": datetime.now(UTC).isoformat(),
            },
        )

    def sync_log(self, step: str, message: str, *, level: str = "info", **detail: Any) -> None:
        """Thread-safe hook for git subprocess steps (called from asyncio.to_thread)."""
        import asyncio

        if not self._emit or not self._loop:
            return
        asyncio.run_coroutine_threadsafe(
            self.log(step, message, level=level, **detail),
            self._loop,
        )
