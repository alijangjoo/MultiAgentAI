"""Detect Cursor CLI failures that should trigger review fallback."""

_CURSOR_CLI_FALLBACK_MARKERS = (
    "not available in your region",
    "connection lost",
    "retriableerror",
    "econnreset",
    "etimedout",
    "network",
    "[unavailable]",
    "unavailable",
)

# Auth / billing errors — 9Router fallback cannot fix these.
_CURSOR_CLI_NO_FALLBACK_MARKERS = (
    "permission_denied",
    "unauthorized",
    "invalid api key",
    "authentication failed",
    "invalid_api_key",
)


def should_fallback_from_cursor_cli(stderr: str, stdout: str = "") -> bool:
    text = f"{stderr}\n{stdout}".lower()
    if any(marker in text for marker in _CURSOR_CLI_NO_FALLBACK_MARKERS):
        return False
    return any(marker in text for marker in _CURSOR_CLI_FALLBACK_MARKERS)


def summarize_cursor_cli_failure(stderr: str, stdout: str = "") -> str:
    """Short user-facing hint from CLI stderr/stdout."""
    text = f"{stderr}\n{stdout}".strip()
    lower = text.lower()
    if "permission_denied" in lower:
        return (
            "Cursor API rejected the request (permission_denied). "
            "Verify CURSOR_API_KEY in .env (Cursor Settings → API), subscription, "
            "and network/proxy access to agentn.global.api5.cursor.sh."
        )
    if "connection lost" in lower or "retriableerror" in lower:
        return (
            "Cursor CLI lost connection to the agent API after retries. "
            "Check internet, VPN/proxy (HTTP_PROXY), firewall, and CURSOR_API_KEY."
        )
    if "not available in your region" in lower:
        return "Cursor agent API is not available in your region."
    if not text:
        return "Cursor CLI failed with no output."
    return text[:500]
