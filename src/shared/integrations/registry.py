from functools import lru_cache

from shared.integrations.factory import IntegrationContainer, build_integrations


@lru_cache
def get_integrations() -> IntegrationContainer:
    """Build integrations lazily on first use (avoids blocking app import)."""
    return build_integrations()
