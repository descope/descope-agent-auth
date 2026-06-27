"""Tiny shared helper for the example scripts: read env vars, fail loudly."""

from __future__ import annotations

import os
import sys


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing required env var: {name}  (see examples/.env.example)")
    return value


def optional(name: str, default: str) -> str:
    return os.environ.get(name) or default


def base_url() -> str:
    return optional("DESCOPE_BASE_URL", "https://api.descope.com")


def preview(token: str) -> str:
    """Show enough of a token to confirm you got one, without dumping the secret."""
    return f"{token[:8]}…{token[-4:]}" if len(token) > 16 else "<short>"
