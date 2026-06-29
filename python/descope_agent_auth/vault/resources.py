"""ResourcesClient -- fetch a Descope **Resource** token.

A Resource is an API you build and protect with Descope acting as the OAuth
authorization server. Unlike a Connection token (a stored API key / provider OAuth
token pulled from the vault), a Resource token is minted on the fly by
**exchanging** the agent's Descope access token for a Resource-scoped token using
the RFC 8693 **token-exchange** grant against the OAuth token endpoint.

Because token-exchange needs an OAuth subject token, this path requires an OAuth
agent identity (Client ID/Secret via any phase-1 provider). It does not apply to a
Management Key.

NOTE: the exact token-exchange parameters (``resource`` vs ``audience``, whether
client auth is also required) should be confirmed against the Descope API
reference; the grant + endpoint are pinned in ``_endpoints``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable, List, Optional

from .._async import maybe_await
from .._endpoints import GRANT_TOKEN_EXCHANGE, OAUTH2_TOKEN, TOKEN_TYPE_ACCESS_TOKEN
from .._http import HttpClient
from ..errors import AgentAuthError, PolicyDenied, TokenExchangeFailed
from ..store.base import TokenStore
from ..types import ApprovalRequest, Credential, Mode, VaultToken


def _cache_key(
    resource: str, scopes: Optional[List[str]], audience: Optional[List[str]]
) -> str:
    scope_part = ",".join(sorted(scopes)) if scopes else "<defaults>"
    aud_part = ",".join(sorted(audience)) if audience else "<none>"
    return f"vault:resource:{resource}:{aud_part}:{scope_part}"


def _err(body: Optional[dict]) -> Optional[str]:
    if not body:
        return None
    return body.get("error_description") or body.get("error") or body.get("errorDescription")


class ResourcesClient:
    def __init__(
        self,
        *,
        http: HttpClient,
        get_credential: Callable[[], Awaitable[Credential]],
        store: TokenStore,
        mode: Mode,
        approval_gate: Optional[Callable[[ApprovalRequest], Awaitable[None]]] = None,
        skew_seconds: float = 60.0,
        cache_tokens: bool = True,
    ) -> None:
        self._http = http
        self._get_credential = get_credential
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
        scopes: Optional[List[str]] = None,
        audience: Optional[List[str]] = None,
        require_approval: Optional[ApprovalRequest] = None,
        force_refresh: bool = False,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        """Mint a Resource token via the token-exchange grant.

        ``resource`` is the RFC 8707 resource indicator (the API you want a token
        for); ``audience`` sets the token-exchange ``audience`` claim when the
        provider requires it. Pass ``act_as_user_token`` to mint a **user-scoped**
        Resource token: that user's Descope access token becomes the ``subject_token``
        of the exchange, instead of the client's own credential.

        Raises ``ApprovalDenied`` / ``ApprovalTimeout`` if a ``require_approval``
        gate fails, ``PolicyDenied`` on 401/403, or ``TokenExchangeFailed`` on
        other failures. In execute mode raw token fetch is disabled (see the
        execution seam).
        """
        if self._mode is Mode.EXECUTE:
            raise AgentAuthError(
                "raw token fetch is disabled in execute mode; the token stays vaulted."
            )

        if require_approval is not None:
            if self._approval_gate is None:
                raise AgentAuthError(
                    "require_approval was set but no approval provider is configured on "
                    "the client; pass approval=CibaProvider(...) to AgentAuthClient"
                )
            await self._approval_gate(require_approval)

        cache_key = _cache_key(resource, scopes, audience)
        if self._cache_tokens and not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached is not None:
                return cached

        # The subject is either an explicit user token (user-scoped) or the
        # client's own credential. A Management Key is not an OAuth token, so it
        # cannot be the subject of a token-exchange.
        if act_as_user_token:
            subject_token = act_as_user_token
        else:
            cred = await self._get_credential()
            if cred.is_privileged:
                raise AgentAuthError(
                    "Resource tokens use the token-exchange grant and require an OAuth "
                    "agent identity (Client ID/Secret via a phase-1 provider) or an "
                    "act_as_user_token, not a Management Key."
                )
            subject_token = cred.token

        data: dict = {
            "grant_type": GRANT_TOKEN_EXCHANGE,
            "subject_token": subject_token,
            "subject_token_type": TOKEN_TYPE_ACCESS_TOKEN,
            "resource": resource,
        }
        if scopes:
            data["scope"] = " ".join(scopes)
        if audience:
            # RFC 8693 audience; sent as repeated form params when multi-valued.
            data["audience"] = audience

        resp = await self._http.post_form(OAUTH2_TOKEN, data=data)
        if resp.status_code in (401, 403):
            raise PolicyDenied(
                f"policy denied for resource '{resource}' "
                f"({resp.status_code}): {_err(resp.json) or resp.text}",
                connection=resource,
                scopes=scopes,
            )
        if not resp.ok or not resp.json or not resp.json.get("access_token"):
            raise TokenExchangeFailed(
                f"resource token-exchange failed ({resp.status_code}): "
                f"{_err(resp.json) or resp.text}",
                status_code=resp.status_code,
            )

        token = self._to_vault_token(resp.json, resource)
        if self._cache_tokens:
            await self._cache_set(cache_key, token)
        return token

    @staticmethod
    def _to_vault_token(body: dict, resource: str) -> VaultToken:
        expires_at: Optional[float] = None
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

    async def _cache_get(self, cache_key: str) -> Optional[VaultToken]:
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
