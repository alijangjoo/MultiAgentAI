"""Detect Cursor CLI failures that should trigger review fallback."""

_CURSOR_CLI_FALLBACK_MARKERS = (
    "not available in your region",
    "permission_denied",
    "connection lost",
    "retriableerror",
    "econnreset",
    "etimedout",
    "network",
    "[unavailable]",
    "unavailable",
)


def should_fallback_from_cursor_cli(stderr: str, stdout: str = "") -> bool:
    text = f"{stderr}\n{stdout}".lower()
    return any(marker in text for marker in _CURSOR_CLI_FALLBACK_MARKERS)
