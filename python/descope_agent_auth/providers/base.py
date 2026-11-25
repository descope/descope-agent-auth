"""The phase-1 credential provider contract.

A provider encodes one acquisition strategy (client credentials, device code,
CIBA, management key, or bring-your-own access token). The client never cares which
provider it holds; it just asks for a current credential and the provider refreshes
transparently underneath.

Credentials are cached in memory and, when the provider exposes a stable storage
key, persisted to the pluggable ``TokenStore`` -- including the refresh token, kept
beyond the access token's expiry so a restarted/multi-process agent can refresh
instead of re-running an interactive flow (device code, CIBA).
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

from .._async import maybe_await
from .._endpoints import GRANT_REFRESH_TOKEN, OAUTH2_TOKEN
from .._http import HttpClient
from ..errors import CredentialAcquisitionFailed
from ..store.base import TokenStore
from ..types import Credential, CredentialKind


class CredentialProvider(ABC):
    """Common interface yielding a valid Descope credential.

    Subclasses implement ``_acquire`` (the actual flow) and, to opt into
    persistence, ``_storage_key`` (a stable key identifying this credential). This
    base handles caching, store load/save, and lazy refresh, so every provider gets
    consistent behavior for free.
    """

    #: Privileged providers (management key) bypass Policies. Surfaced so downstream
    #: code and logging can treat that path with caution.
    kind: CredentialKind = CredentialKind.AGENT_TOKEN

    #: Token endpoint for the ``refresh_token`` grant: the one that issued the token.
    refresh_endpoint: str = OAUTH2_TOKEN

    #: True when this provider's identity *is* the agent client (client
    #: credentials). A Resource token the agent requests as itself then uses the
    #: ``client_credentials`` grant, which Descope's client-access Policies govern.
    #: False means the provider's credential is exchanged instead (RFC 8693), e.g.
    #: a CIBA token that represents a user. ``kind`` can't carry this: other
    #: providers (JWT bearer) are ``AGENT_TOKEN`` too.
    acts_as_client: bool = False

    def __init__(self) -> None:
        self._cached: Credential | None = None
        # Bound by AgentAuthClient at init so providers can talk to Descope + persist.
        self._http: HttpClient | None = None
        self._project_id: str | None = None
        self._store: TokenStore | None = None

    # -- wired by the client ------------------------------------------------

    def bind(self, http: HttpClient, project_id: str, store: TokenStore | None = None) -> None:
        self._http = http
        self._project_id = project_id
        self._store = store

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            raise CredentialAcquisitionFailed(
                "provider is not bound to a client; construct it via AgentAuthClient"
            )
        return self._http

    # -- public API ---------------------------------------------------------

    async def get_credential(self) -> Credential:
        """Return a current, valid credential, refreshing/acquiring as needed."""
        if self._cached is not None and not self._cached.is_expired():
            return self._cached

        # Cold start: nothing in memory -> try the store (survives restarts).
        if self._cached is None:
            loaded = await self._load()
            if loaded is not None:
                self._cached = loaded
                if not loaded.is_expired():
                    return loaded

        # Held credential is expired (or near). Refresh if we have a refresh token,
        # else acquire fresh.
        if self._cached is not None and self._cached.refresh_token:
            try:
                self._cached = await self._refresh(self._cached)
                await self._save(self._cached)
                return self._cached
            except CredentialAcquisitionFailed:
                pass  # fall through to a fresh acquisition

        self._cached = await self._acquire()
        await self._save(self._cached)
        return self._cached

    async def refresh(self) -> Credential:
        """Force a refresh (or re-acquire if no refresh token is held)."""
        base = self._cached or await self._load()
        if base is not None and base.refresh_token:
            self._cached = await self._refresh(base)
        else:
            self._cached = await self._acquire()
        await self._save(self._cached)
        return self._cached

    @property
    def is_privileged(self) -> bool:
        return self.kind.is_privileged

    # -- subclass hooks -----------------------------------------------------

    @abstractmethod
    async def _acquire(self) -> Credential:
        """Run the provider's flow and return a fresh credential."""

    def _storage_key(self) -> str | None:
        """A stable key under which to persist this credential, or ``None`` to skip
        persistence (e.g. management key, bring-your-own token)."""
        return None

    async def _refresh(self, current: Credential) -> Credential:
        """Default refresh via the OAuth2 ``refresh_token`` grant.

        Providers without a refresh token (or with a bespoke flow) override this.
        """
        if not current.refresh_token:
            return await self._acquire()
        data = {
            "grant_type": GRANT_REFRESH_TOKEN,
            "refresh_token": current.refresh_token,
        }
        data.update(self._refresh_client_auth())
        resp = await self.http.post_form(self.refresh_endpoint, data=data)
        if not resp.ok:
            raise CredentialAcquisitionFailed(
                f"refresh failed ({resp.status_code}): {_err(resp.json) or resp.text}"
            )
        return token_response_to_credential(resp.json, kind=self.kind, fallback=current)

    def _refresh_client_auth(self) -> dict[str, str]:
        """Extra form fields / client auth needed for refresh. Override as needed."""
        return {}

    def client_auth(self) -> dict[str, str] | None:
        """Form fields that authenticate this agent as a confidential client.

        Resource tokens are minted by an authenticated agent client (it becomes
        ``act.sub`` on a token exchange). Providers that hold a client secret
        return ``client_id`` + ``client_secret``; the rest return ``None`` and
        cannot mint Resource tokens.
        """
        return None

    def identity_key(self) -> str | None:
        """A stable id for whom this provider's own credential represents, or ``None``.

        When a Resource token is minted by exchanging this provider's own credential,
        the token cache is keyed by this id instead of a digest of the current
        credential. A cached Resource token is then served without first refreshing
        (or re-approving) the credential, and survives its rotation. Override only
        when the id pins down one subject: two providers that may hold different
        users' credentials must never return the same id. The default ``None`` keys
        by the credential itself.
        """
        return None

    # -- persistence --------------------------------------------------------

    async def _save(self, cred: Credential) -> None:
        key = self._storage_key()
        if key is None or self._store is None:
            return
        payload = json.dumps(
            {
                "token": cred.token,
                "kind": cred.kind.value,
                "expires_at": cred.expires_at,
                "refresh_token": cred.refresh_token,
                "scope": cred.scope,
            }
        )
        # No TTL: the refresh token must outlive the access token's expiry, so the
        # entry persists until overwritten. Expiry is decided from cred.expires_at.
        await maybe_await(self._store.set(key, payload))

    async def _load(self) -> Credential | None:
        key = self._storage_key()
        if key is None or self._store is None:
            return None
        raw = await maybe_await(self._store.get(key))
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        try:
            kind = CredentialKind(obj.get("kind", CredentialKind.AGENT_TOKEN.value))
        except ValueError:
            kind = CredentialKind.AGENT_TOKEN
        return Credential(
            token=obj["token"],
            kind=kind,
            expires_at=obj.get("expires_at"),
            refresh_token=obj.get("refresh_token"),
            scope=obj.get("scope"),
        )


def token_response_to_credential(
    body: dict[str, Any] | None,
    *,
    kind: CredentialKind,
    fallback: Credential | None = None,
) -> Credential:
    """Parse a standard OAuth2 token response into a ``Credential``."""
    if not body or "access_token" not in body:
        raise CredentialAcquisitionFailed("token response missing access_token")
    expires_at: float | None = None
    if isinstance(body.get("expires_in"), (int, float)):
        expires_at = time.time() + float(body["expires_in"])
    refresh = body.get("refresh_token")
    if refresh is None and fallback is not None:
        refresh = fallback.refresh_token  # refresh responses often omit a new one
    scope = body.get("scope")
    if not (isinstance(scope, str) and scope):
        # RFC 6749 5.1: a response may omit scope when it is unchanged.
        scope = fallback.scope if fallback is not None else None
    authorization_details = body.get("authorization_details")
    return Credential(
        token=str(body["access_token"]),
        kind=kind,
        expires_at=expires_at,
        refresh_token=refresh,
        scope=scope,
        authorization_details=(
            authorization_details if isinstance(authorization_details, list) else None
        ),
    )


def _err(body: dict[str, Any] | None) -> str | None:
    if not body:
        return None
    return body.get("error_description") or body.get("error") or body.get("errorDescription")
