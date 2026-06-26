"""Shared types for the Descope Agent Auth SDK.

These are intentionally plain dataclasses / enums with no behavior so they can be
returned across the public API surface without leaking implementation details.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class CredentialKind(str, Enum):
    """How a phase-1 credential is governed downstream.

    ``AGENT_TOKEN`` credentials are subject to Connection Policies at exchange
    time. ``MANAGEMENT_KEY`` credentials bypass those policies entirely and grant
    broad vault access -- this is never the recommended path.
    """

    AGENT_TOKEN = "agent_token"
    MANAGEMENT_KEY = "management_key"

    @property
    def is_privileged(self) -> bool:
        return self is CredentialKind.MANAGEMENT_KEY


class Mode(str, Enum):
    """The execution seam (see ``execution`` module / spec).

    ``FETCH`` returns the raw downstream token to the caller (ships today).
    ``EXECUTE`` is reserved for the future hosted-execution endpoint, where the
    token stays vaulted and only the call result returns.
    """

    FETCH = "fetch"
    EXECUTE = "execute"


@dataclass(frozen=True)
class Credential:
    """A phase-1 Descope credential held by a provider.

    ``token`` is the bearer value used to authenticate to Descope: either an
    acquired access token or a static management key. ``expires_at`` is a unix
    timestamp; ``None`` means the credential does not expire on its own (e.g. a
    management key).
    """

    token: str
    kind: CredentialKind
    expires_at: Optional[float] = None
    refresh_token: Optional[str] = None

    @property
    def is_privileged(self) -> bool:
        return self.kind.is_privileged

    def is_expired(self, *, skew_seconds: float = 60.0) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - skew_seconds)


@dataclass(frozen=True)
class VaultToken:
    """A downstream token returned from the Descope vault (phase 2).

    ``access_token`` is the provider token (GitHub, Slack, ...) or resource token
    the caller actually uses. The remaining fields mirror the Descope outbound
    token object so callers can introspect without a second round trip.
    """

    access_token: str
    token_type: str = "Bearer"
    expires_at: Optional[float] = None
    scopes: List[str] = field(default_factory=list)
    refresh_token: Optional[str] = None
    has_refresh_token: bool = False
    app_id: Optional[str] = None
    user_id: Optional[str] = None
    raw: Optional[dict] = None

    def is_expired(self, *, skew_seconds: float = 60.0) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - skew_seconds)

    def __str__(self) -> str:  # never leak the token in logs/str()
        return f"VaultToken(app_id={self.app_id!r}, scopes={self.scopes!r}, expires_at={self.expires_at!r})"

    __repr__ = __str__


@dataclass(frozen=True)
class PendingAuthorization:
    """A user-action-required state surfaced by interactive phase-1 flows.

    Device code and CIBA both produce one of these on first use: the caller shows
    the user what to do (visit a URL, enter a code, approve a push), then the SDK
    polls to completion.
    """

    # Device code fields
    verification_uri: Optional[str] = None
    verification_uri_complete: Optional[str] = None
    user_code: Optional[str] = None
    # Shared
    expires_at: Optional[float] = None
    interval_seconds: float = 5.0
    message: Optional[str] = None
    raw: Optional[dict] = None


@dataclass(frozen=True)
class ApprovalRequest:
    """A just-in-time CIBA approval gate for a single sensitive exchange/action.

    Distinct from acquisition: the agent already holds a working credential, but a
    real person must sign off on a trusted device before this one step proceeds.
    """

    login_hint: str
    binding_message: Optional[str] = None
    scopes: Optional[List[str]] = None
    timeout_seconds: float = 120.0
