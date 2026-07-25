"""Map review model names to Cursor CLI-compatible IDs."""

_DEFAULT_CURSOR_REVIEW_MODEL = "composer-2.5"

# 9Router / multi-provider prefixes — not valid for Cursor CLI `agent --model`.
_PROVIDER_PREFIXES = ("oc/", "cu/", "cc/", "ag/", "cx/", "gh/", "kr/")

# Names that were used with 9Router/OpenAI and should not be sent to Cursor CLI.
_LEGACY_NON_CURSOR_MODELS = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    }
)

# Account-specific alias when composer-2.5-fast is requested but unavailable.
_CURSOR_MODEL_ALIASES = {
    "composer-2.5-fast": "composer-2.5",
    "composer-2": "composer-2.5",
    "auto": "composer-2.5",
}


def normalize_cursor_cli_model(
    model: str | None,
    *,
    default: str = _DEFAULT_CURSOR_REVIEW_MODEL,
) -> str:
    """Return a model slug accepted by `agent --model` (never 9Router-prefixed IDs)."""
    chosen = (model or "").strip()
    if not chosen:
        return default

    lowered = chosen.lower()
    if lowered.startswith(_PROVIDER_PREFIXES):
        return default

    if lowered in _LEGACY_NON_CURSOR_MODELS:
        return default

    return _CURSOR_MODEL_ALIASES.get(lowered, chosen)
