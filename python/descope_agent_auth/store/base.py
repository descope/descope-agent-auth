"""Pluggable token cache interface.

A ``TokenStore`` caches both the phase-1 Descope credential and the phase-2
downstream tokens. Refresh is the caller layers' job; the store is a dumb
key/value cache with a TTL hint, so it can be backed by memory, Redis, a
database, or a secrets manager without changing the SDK.

Implementations MUST NOT log stored values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class TokenStore(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Return the stored value, or ``None`` if absent."""

    @abstractmethod
    def set(self, key: str, value: str, *, ttl_seconds: Optional[float] = None) -> None:
        """Store ``value`` under ``key``. ``ttl_seconds`` is an optional expiry hint."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove ``key`` if present (no error if absent)."""

    @abstractmethod
    def list(self) -> List[str]:
        """Return the currently-stored (non-expired) keys."""
