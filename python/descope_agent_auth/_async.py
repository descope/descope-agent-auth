"""Small async helpers shared across the async core.

The TokenStore ABC is intentionally sync-compatible: an implementation may return
plain values (the default ``MemoryTokenStore``) or awaitables (a Redis/async store).
The async core never assumes which: it routes every store call through
``maybe_await`` so both shapes work.
"""

from __future__ import annotations

import inspect
from typing import Any


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
