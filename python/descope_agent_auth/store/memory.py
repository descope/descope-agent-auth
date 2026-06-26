"""In-memory token store: the default, fine for single-process agents."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .base import TokenStore


@dataclass
class _Entry:
    value: str
    expires_at: Optional[float]

    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at


class MemoryTokenStore(TokenStore):
    def __init__(self) -> None:
        self._data: Dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del self._data[key]
                return None
            return entry.value

    def set(self, key: str, value: str, *, ttl_seconds: Optional[float] = None) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        with self._lock:
            self._data[key] = _Entry(value=value, expires_at=expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def list(self) -> List[str]:
        with self._lock:
            keys = []
            for key, entry in list(self._data.items()):
                if entry.is_expired():
                    del self._data[key]
                else:
                    keys.append(key)
            return keys
