"""ResourcesClient -- fetch a Descope **Resource** token.

A Resource is an API you build and protect with Descope acting as the OAuth
authorization server. Unlike a Connection token (a stored API key / provider OAuth
token pulled from the vault), a Resource token is minted on the fly at the
inbound-apps token endpoint (``/oauth2/v1/apps/token``, per the
``/v1/apps/<projectId>`` discovery document), always authenticated by a
confidential agent client (``client_id`` + ``client_secret``). Two grants apply:

- **The agent acting as itself** (a ``ClientCredentialsProvider`` client, no
  ``act_as_user_token``): a ``client_credentials`` request that names the
  ``resource``. Descope's client-access Policies decide which scopes it gets.
- **The agent acting for a subject** (``act_as_user_token``, or a phase-1
  credential that represents a user, such as CIBA): an RFC 8693 token exchange of
  that subject token. Descope's token-exchange Policies decide the scopes, and the
  authenticating client is recorded as ``act.sub`` so the downstream API can see
  which agent is acting for the user.

A Management Key cannot mint Resource tokens.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .._async import maybe_await
from .._endpoints import (
    GRANT_CLIENT_CREDENTIALS,
    GRANT_TOKEN_EXCHANGE,
    OAUTH2_APPS_TOKEN,
    TOKEN_TYPE_ACCESS_TOKEN,
)
from .._http import HttpClient
from ..errors import (
    AgentAuthError,
    CredentialAcquisitionFailed,
    PolicyDenied,
    TokenExchangeFailed,
)
from ..store.base import TokenStore
from ..types import ApprovalRequest, Credential, Mode, VaultToken


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cache_key(
    resource: str,
    scopes: list[str] | None,
    audience: list[str] | None,
    *,
    client_id: str,
    subject: str,
) -> str:
    scope_part = ",".join(sorted(scopes)) if scopes else "<defaults>"
    aud_part = ",".join(sorted(audience)) if audience else "<none>"
    # A Resource token belongs to one (actor, subject) pair: the client that
    # authenticates the request (act.sub on an exchange) and the subject. Key by
    # both so a shared TokenStore never serves one client's or one user's token to
    # another. ``subject`` is "self" (client_credentials), a digest of the token
    # being exchanged, or "id:" + a digest of the provider's stable identity (see
    # CredentialProvider.identity_key). No raw token or identity lands in the key.
    return f"vault:resource:{client_id}:{subject}:{resource}:{aud_part}:{scope_part}"


def _err(body: dict[str, Any] | None) -> str | None:
    if not body:
        return None
    return (
        body.get("error_description")
        or body.get("errorMessage")
        or body.get("error")
        or body.get("errorDescription")
    )


# OAuth error codes (RFC 6749 / 8693 / 8707) that mean "no Policy grants this".
_POLICY_ERRORS = frozenset({"unauthorized_client", "invalid_target", "access_denied"})
# Descope's own codes for the same, sent in the legacy envelope (``errorCode``):
# E063309 for the agent's own token, E063313 when acting for a user.
_POLICY_ERROR_CODES = frozenset({"E063309", "E063313"})
_SCOPE_NOT_GRANTED = "requested scope not granted"


def _token_error_class(status_code: int, body: Any) -> str:
    """Classify a failed Resource token response by the error the server returns.

    Returns ``"client"`` (the agent's client auth was rejected), ``"policy"`` (no
    Policy grants the request), or ``"other"``. Every request carries the client
    secret, so a 401 is usually a bad secret, not a Policy decision: go by the
    OAuth ``error`` rather than the HTTP status. Descope can also send its legacy
    envelope (strict OAuth errors off), where ``errorDescription`` carries the
    OAuth code and ``errorCode`` / ``errorMessage`` Descope's own code and reason.
    """
    b = body if isinstance(body, dict) else {}
    codes = {b.get("error"), b.get("errorDescription")}
    if "invalid_client" in codes:
        return "client"
    if codes & _POLICY_ERRORS or b.get("errorCode") in _POLICY_ERROR_CODES:
        return "policy"
    reason = " ".join(
        str(v) for v in (b.get("error_description"), b.get("errorMessage")) if v
    ).lower()
    if _SCOPE_NOT_GRANTED in reason or status_code == 403:
        return "policy"
    return "other"


class ResourcesClient:
    def __init__(
        self,
        *,
        http: HttpClient,
        get_credential: Callable[[], Awaitable[Credential]],
        get_client_auth: Callable[[], dict[str, str] | None],
        store: TokenStore,
        mode: Mode,
        approval_gate: Callable[[ApprovalRequest], Awaitable[None]] | None = None,
        skew_seconds: float = 60.0,
        cache_tokens: bool = True,
        acts_as_client: bool = False,
        get_identity_key: Callable[[], str | None] | None = None,
    ) -> None:
        self._http = http
        self._get_credential = get_credential
        self._get_client_auth = get_client_auth
        # True when the provider's identity is the agent client: its own Resource
        # tokens use client_credentials rather than exchanging the credential.
        self._acts_as_client = acts_as_client
        # The provider's stable identity, when it has one (CIBA: client + user).
        self._get_identity_key = get_identity_key
        self._store = store
        self._mode = mode
        self._approval_gate = approval_gate
        self._skew = skew_seconds
        # When False, never read/write the token cache: every mint hits Descope so
        # Policies are re-enforced each call (see VaultBackend for the rationale).
        self._cache_tokens = cache_tokens

    async def get_token(
        self,
        *,
        resource: str,
        scopes: list[str] | None = None,
        audience: list[str] | None = None,
        require_approval: ApprovalRequest | None = None,
        force_refresh: bool = False,
        act_as_user_token: str | None = None,
    ) -> VaultToken:
        """Mint a Resource token.

        ``resource`` is the RFC 8707 resource indicator (the API you want a token
        for); ``audience`` sets the token-exchange ``audience`` claim when the
        provider requires it. Pass ``act_as_user_token`` to mint a **user-scoped**
        Resource token: that user's Descope access token becomes the ``subject_token``
        of a token exchange. Without it, a ``ClientCredentialsProvider`` client
        requests the token for itself with the ``client_credentials`` grant, and
        other providers exchange their own phase-1 credential.

        Raises ``ApprovalDenied`` / ``ApprovalTimeout`` if a ``require_approval``
        gate fails, ``CredentialAcquisitionFailed`` when Descope rejects the agent
        client (``invalid_client``: wrong ID or secret), ``PolicyDenied`` when no
        Policy grants the request (``unauthorized_client``, ``invalid_target``,
        ``access_denied``, a scope not granted, or a 403), or ``TokenExchangeFailed``
        on other failures. In execute mode raw token fetch is disabled (see the
        execution seam).
        """
        if self._mode is Mode.EXECUTE:
            raise AgentAuthError(
                "raw token fetch is disabled in execute mode; the token stays vaulted."
            )

        # Descope rejects unauthenticated token-exchange requests, and the
        # authenticating client is what lands in act.sub. Fail before any network
        # call (or approval prompt) when the provider has no client secret to offer.
        client_auth = self._get_client_auth()
        if not client_auth:
            raise AgentAuthError(
                "Resource tokens use the token-exchange grant, which Descope only serves "
                "to an authenticated agent client. Configure the client with "
                "ClientCredentialsProvider(client_id=..., client_secret=...) and pass "
                "act_as_user_token=... to act for a user."
            )

        if require_approval is not None:
            if self._approval_gate is None:
                raise AgentAuthError(
                    "require_approval was set but no approval provider is configured on "
                    "the client; pass approval=CibaProvider(...) to AgentAuthClient"
                )
            await self._approval_gate(require_approval)

        # The subject is an explicit user token (user-scoped), nothing (a
        # client-credentials agent acting as itself), or the client's own phase-1
        # credential. The cache key is bound to the subject. For the own-credential
        # path, a provider with a stable identity (CIBA: one user) is keyed by that
        # identity, so a cached Resource token is served without touching -- and
        # possibly refreshing or re-approving -- the phase-1 credential, and the
        # entry survives that credential's rotation. Without one, the credential
        # must be resolved first so its digest can key the entry.
        as_self = not act_as_user_token and self._acts_as_client
        subject_token: str | None = act_as_user_token or None
        if act_as_user_token:
            subject = _digest(act_as_user_token)
        elif as_self:
            subject = "self"
        else:
            identity = self._get_identity_key() if self._get_identity_key else None
            if identity:
                subject = "id:" + _digest(identity)
            else:
                subject_token = await self._own_subject_token()
                subject = _digest(subject_token)

        cache_key = _cache_key(
            resource,
            scopes,
            audience,
            client_id=client_auth.get("client_id", ""),
            subject=subject,
        )
        if self._cache_tokens and not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached is not None:
                return cached
        if not as_self and subject_token is None:
            subject_token = await self._own_subject_token()

        data: dict[str, Any]
        if as_self:
            # The agent acting as itself: Descope applies client-access Policies
            # only to a client_credentials request that names the resource.
            data = {
                "grant_type": GRANT_CLIENT_CREDENTIALS,
                "resource": resource,
                **client_auth,
            }
        else:
            data = {
                "grant_type": GRANT_TOKEN_EXCHANGE,
                "subject_token": subject_token,
                "subject_token_type": TOKEN_TYPE_ACCESS_TOKEN,
                "resource": resource,
                **client_auth,
            }
        if scopes:
            data["scope"] = " ".join(scopes)
        if audience:
            # RFC 8693 audience; sent as repeated form params when multi-valued.
            data["audience"] = audience

        resp = await self._http.post_form(OAUTH2_APPS_TOKEN, data=data)
        if not resp.ok:
            reason = _err(resp.json) or resp.text
            error_class = _token_error_class(resp.status_code, resp.json)
            if error_class == "client":
                raise CredentialAcquisitionFailed(
                    f"Descope rejected the agent client ({resp.status_code}): {reason}. "
                    "Check the client_id and client_secret."
                )
            if error_class == "policy":
                raise PolicyDenied(
                    f"policy denied for resource '{resource}' ({resp.status_code}): {reason}",
                    connection=resource,
                    scopes=scopes,
                )
        if not resp.ok or not resp.json or not resp.json.get("access_token"):
            raise TokenExchangeFailed(
                f"resource token request failed ({resp.status_code}): "
                f"{_err(resp.json) or resp.text}",
                status_code=resp.status_code,
            )

        token = self._to_vault_token(resp.json, resource)
        if self._cache_tokens:
            await self._cache_set(cache_key, token)
        return token

    async def _own_subject_token(self) -> str:
        # The client's own phase-1 credential as the exchange subject. A Management
        # Key is not an OAuth token, so it cannot be the subject of a token exchange.
        cred = await self._get_credential()
        if cred.is_privileged:
            raise AgentAuthError(
                "Resource tokens use the token-exchange grant and require an OAuth "
                "agent identity (Client ID/Secret via a phase-1 provider) or an "
                "act_as_user_token, not a Management Key."
            )
        return cred.token

    @staticmethod
    def _to_vault_token(body: dict[str, Any], resource: str) -> VaultToken:
        expires_at: float | None = None
        if isinstance(body.get("expires_in"), (int, float)):
            expires_at = time.time() + float(body["expires_in"])
        scope = body.get("scope")
        scopes = scope.split() if isinstance(scope, str) and scope else []
        return VaultToken(
            access_token=str(body["access_token"]),
            token_type=body.get("token_type") or "Bearer",
            expires_at=expires_at,
            scopes=scopes,
            app_id=resource,
            raw={k: v for k, v in body.items() if k != "access_token"},
        )

    # -- cache --------------------------------------------------------------

    async def _cache_get(self, cache_key: str) -> VaultToken | None:
        raw = await maybe_await(self._store.get(cache_key))
        if raw is None:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        token = VaultToken(
            access_token=obj.get("access_token", ""),
            token_type=obj.get("token_type", "Bearer"),
            expires_at=obj.get("expires_at"),
            scopes=list(obj.get("scopes") or []),
            app_id=obj.get("app_id"),
        )
        if token.is_expired(skew_seconds=self._skew):
            await maybe_await(self._store.delete(cache_key))
            return None
        return token

    async def _cache_set(self, cache_key: str, token: VaultToken) -> None:
        payload: dict[str, Any] = {
            "access_token": token.access_token,
            "token_type": token.token_type,
            "expires_at": token.expires_at,
            "scopes": token.scopes,
            "app_id": token.app_id,
        }
        ttl = None
        if token.expires_at is not None:
            ttl = max(0.0, token.expires_at - time.time())
        await maybe_await(self._store.set(cache_key, json.dumps(payload), ttl_seconds=ttl))
