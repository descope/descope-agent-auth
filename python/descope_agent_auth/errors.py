"""Typed errors for the Descope Agent Auth SDK.

Each error is specific enough that a coding agent generating an integration can
handle the re-auth and approval cases correctly without guessing. The headline
case -- "connection not yet authorized" -- is modeled as a first-class signal
carrying the connect URL the caller redirects the user to.
"""

from __future__ import annotations

from typing import List, Optional


class AgentAuthError(Exception):
    """Base class for all SDK errors."""


class ConnectionAuthorizationRequired(AgentAuthError):
    """The user has not yet connected (or has revoked) the downstream account.

    Catch this and redirect the user to ``connect_url`` to complete the OAuth
    consent, then retry the exchange.
    """

    def __init__(
        self,
        message: str,
        *,
        connect_url: Optional[str] = None,
        connection: Optional[str] = None,
        identifier: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.connect_url = connect_url
        self.connection = connection
        self.identifier = identifier


class PolicyDenied(AgentAuthError):
    """The agent token lacks Policy permission for this connection/scope."""

    def __init__(
        self,
        message: str,
        *,
        connection: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> None:
        super().__init__(message)
        self.connection = connection
        self.scopes = scopes


class CredentialAcquisitionFailed(AgentAuthError):
    """Phase 1 failed: bad client credentials, device-flow timeout, etc."""


class TokenExchangeFailed(AgentAuthError):
    """Phase 2 transport or validation failure not covered by a more specific error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApprovalDenied(AgentAuthError):
    """The CIBA gate: the user explicitly rejected the request."""


class ApprovalTimeout(AgentAuthError):
    """The CIBA gate: the user did not respond before the request expired."""


class AuthorizationPending(AgentAuthError):
    """Internal: the user has not yet completed an interactive flow (device/CIBA).

    Surfaced during polling; the SDK handles this internally and does not normally
    raise it to callers.
    """
