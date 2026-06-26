"""The phase-1 credential provider contract.

A provider encodes one acquisition strategy (client credentials, device code,
authorization code, CIBA, management key). The client never cares which provider
it holds -- it just asks for a current credential and the provider refreshes
transparently underneath.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

from .._endpoints import GRANT_REFRESH_TOKEN, OAUTH2_TOKEN
from .._http import HttpClient
from ..errors import CredentialAcquisitionFailed
from ..types import Credential, CredentialKind


class CredentialProvider(ABC):
    """Common interface yielding a valid Descope credential.

    Subclasses implement ``_acquire`` (the actual flow). This base handles caching
    the current credential and lazy refresh, so every provider gets consistent
    refresh-on-get behavior for free.
    """

    #: Privileged providers (management key) bypass Policies. Surfaced
    #: so downstream code and logging can treat that path with caution.
    kind: CredentialKind = CredentialKind.AGENT_TOKEN

    def __init__(self) -> None:
        self._cached: Optional[Credential] = None
        # Bound by AgentAuthClient at init so providers can talk to Descope.
        self._http: Optional[HttpClient] = None
        self._project_id: Optional[str] = None

    # -- wired by the client ------------------------------------------------

    def bind(self, http: HttpClient, project_id: str) -> None:
        self._http = http
        self._project_id = project_id

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            raise CredentialAcquisitionFailed(
                "provider is not bound to a client; construct it via AgentAuthClient"
            )
        return self._http

    # -- public API ---------------------------------------------------------

    def get_credential(self) -> Credential:
        """Return a current, valid credential, refreshing/acquiring as needed."""
        if self._cached is not None and not self._cached.is_expired():
            return self._cached
        if self._cached is not None and self._cached.refresh_token:
            try:
                self._cached = self._refresh(self._cached)
                return self._cached
            except CredentialAcquisitionFailed:
                pass  # fall through to a fresh acquisition
        self._cached = self._acquire()
        return self._cached

    def refresh(self) -> Credential:
        """Force a refresh (or re-acquire if no refresh token is held)."""
        if self._cached is not None and self._cached.refresh_token:
            self._cached = self._refresh(self._cached)
        else:
            self._cached = self._acquire()
        return self._cached

    @property
    def is_privileged(self) -> bool:
        return self.kind.is_privileged

    # -- subclass hooks -----------------------------------------------------

    @abstractmethod
    def _acquire(self) -> Credential:
        """Run the provider's flow and return a fresh credential."""

    def _refresh(self, current: Credential) -> Credential:
        """Default refresh via the OAuth2 ``refresh_token`` grant.

        Providers without a refresh token (or with a bespoke flow) override this.
        """
        if not current.refresh_token:
            return self._acquire()
        data = {
            "grant_type": GRANT_REFRESH_TOKEN,
            "refresh_token": current.refresh_token,
        }
        data.update(self._refresh_client_auth())
        resp = self.http.post_form(OAUTH2_TOKEN, data=data)
        if not resp.ok:
            raise CredentialAcquisitionFailed(
                f"refresh failed ({resp.status_code}): {_err(resp.json) or resp.text}"
            )
        return token_response_to_credential(resp.json, kind=self.kind, fallback=current)

    def _refresh_client_auth(self) -> dict:
        """Extra form fields / client auth needed for refresh. Override as needed."""
        return {}


def token_response_to_credential(
    body: Optional[dict],
    *,
    kind: CredentialKind,
    fallback: Optional[Credential] = None,
) -> Credential:
    """Parse a standard OAuth2 token response into a ``Credential``."""
    if not body or "access_token" not in body:
        raise CredentialAcquisitionFailed("token response missing access_token")
    expires_at: Optional[float] = None
    if isinstance(body.get("expires_in"), (int, float)):
        expires_at = time.time() + float(body["expires_in"])
    refresh = body.get("refresh_token")
    if refresh is None and fallback is not None:
        refresh = fallback.refresh_token  # refresh responses often omit a new one
    return Credential(
        token=str(body["access_token"]),
        kind=kind,
        expires_at=expires_at,
        refresh_token=refresh,
    )


def _err(body: Optional[dict]) -> Optional[str]:
    if not body:
        return None
    return body.get("error_description") or body.get("error") or body.get("errorDescription")
