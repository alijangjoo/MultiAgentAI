import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_sync(func: Callable[..., T], *args, **kwargs) -> T:
    """Run blocking SDK calls without blocking the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)
