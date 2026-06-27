"""Shared phase-2 exchange machinery.

Both ConnectionsClient and ResourcesClient consume whatever phase-1 credential
the client holds, build the management-style bearer header
(``Bearer <project_id>:<credential>``), call an outbound token endpoint, and map
the result -- including the headline 404 -> ConnectionAuthorizationRequired path.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from .._async import maybe_await
from .._endpoints import OUTBOUND_CONNECT
from .._http import HttpClient
from ..errors import (
    AgentAuthError,
    ConnectionAuthorizationRequired,
    PolicyDenied,
    TokenExchangeFailed,
)
from ..store.base import TokenStore
from ..types import ApprovalRequest, Credential, VaultToken


def _parse_expiry(value: Any) -> Optional[float]:
    """Map Descope's accessTokenExpiry (epoch number or RFC3339 string) to unix time."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Heuristic: treat very large values as milliseconds.
        return float(value) / 1000.0 if value > 1e12 else float(value)
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return None
    return None


def token_object_to_vault_token(obj: dict) -> VaultToken:
    return VaultToken(
        access_token=str(obj.get("accessToken", "")),
        token_type=obj.get("accessTokenType") or "Bearer",
        expires_at=_parse_expiry(obj.get("accessTokenExpiry")),
        scopes=list(obj.get("scopes") or []),
        refresh_token=obj.get("refreshToken"),
        has_refresh_token=bool(obj.get("hasRefreshToken")),
        app_id=obj.get("appId"),
        user_id=obj.get("userId"),
        raw={k: v for k, v in obj.items() if k not in ("accessToken", "refreshToken")},
    )


class VaultBackend:
    def __init__(
        self,
        *,
        http: HttpClient,
        project_id: str,
        get_credential: Callable[[], Awaitable[Credential]],
        store: TokenStore,
        approval_gate: Optional[Callable[["ApprovalRequest"], Awaitable[None]]] = None,
        skew_seconds: float = 60.0,
    ) -> None:
        self._http = http
        self._project_id = project_id
        self._get_credential = get_credential
        self._store = store
        # Runs a CIBA approval before a sensitive exchange; raises on denial/timeout.
        self._approval_gate = approval_gate
        self._skew = skew_seconds

    # -- auth ---------------------------------------------------------------

    async def _auth_header(self) -> tuple:
        """Return (header_value, is_privileged) for the current credential."""
        cred = await self._get_credential()
        return f"Bearer {self._project_id}:{cred.token}", cred.is_privileged

    # -- cache --------------------------------------------------------------

    async def _cache_get(self, cache_key: str) -> Optional[VaultToken]:
        raw = await maybe_await(self._store.get(cache_key))
        if raw is None:
            return None
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            return None
        token = token_object_to_vault_token(obj)
        if token.is_expired(skew_seconds=self._skew):
            await maybe_await(self._store.delete(cache_key))
            return None
        return token

    async def _cache_set(self, cache_key: str, token: VaultToken) -> None:
        payload = dict(token.raw or {})
        payload["accessToken"] = token.access_token
        ttl = None
        if token.expires_at is not None:
            ttl = max(0.0, token.expires_at - time.time())
        await maybe_await(self._store.set(cache_key, json.dumps(payload), ttl_seconds=ttl))

    # -- exchange -----------------------------------------------------------

    async def fetch(
        self,
        *,
        path: str,
        body: dict,
        cache_key: str,
        connection: str,
        identifier: Optional[str],
        connect_body: Optional[dict],
        force_refresh: bool,
        require_approval: Optional["ApprovalRequest"] = None,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        # Phase-2 CIBA gate: a real person must sign off before this sensitive
        # exchange proceeds. Runs before any cache hit so the approval is never
        # skipped for a cached token.
        if require_approval is not None:
            if self._approval_gate is None:
                raise AgentAuthError(
                    "require_approval was set but no approval provider is configured on "
                    "the client; pass approval=CibaProvider(...) to AgentAuthClient"
                )
            await self._approval_gate(require_approval)

        if not force_refresh:
            cached = await self._cache_get(cache_key)
            if cached is not None:
                return cached

        # act_as_user_token: present a specific user's Descope access token for this
        # call so the vault fetch is user-scoped, instead of the client's credential.
        if act_as_user_token:
            header = f"Bearer {self._project_id}:{act_as_user_token}"
        else:
            header, _privileged = await self._auth_header()
        resp = await self._http.post_json(
            path, json=body, headers={"Authorization": header, "Content-Type": "application/json"}
        )

        if resp.ok and resp.json and resp.json.get("token"):
            token = token_object_to_vault_token(resp.json["token"])
            await self._cache_set(cache_key, token)
            return token

        # 404 -> user has not connected (or token cleared / wrong scopes).
        if resp.status_code == 404:
            connect_url = await self._try_connect_url(connect_body, header)
            raise ConnectionAuthorizationRequired(
                f"connection '{connection}' is not authorized for this identity yet",
                connect_url=connect_url,
                connection=connection,
                identifier=identifier,
            )

        # 401/403 -> Policy (or auth) denied. Meaningful for agent tokens;
        # a management key is unrestricted, so a 403 there is a real config error.
        if resp.status_code in (401, 403):
            raise PolicyDenied(
                f"policy denied for connection '{connection}' "
                f"({resp.status_code}): {_msg(resp.json) or resp.text}",
                connection=connection,
                scopes=body.get("scopes"),
            )

        raise TokenExchangeFailed(
            f"token exchange failed ({resp.status_code}): {_msg(resp.json) or resp.text}",
            status_code=resp.status_code,
        )

    async def _try_connect_url(self, connect_body: Optional[dict], header: str) -> Optional[str]:
        if connect_body is None:
            return None
        try:
            resp = await self._http.post_json(
                OUTBOUND_CONNECT,
                json=connect_body,
                headers={"Authorization": header, "Content-Type": "application/json"},
            )
            if resp.ok and resp.json:
                return resp.json.get("url")
        except AgentAuthError:
            return None
        return None


def _msg(body: Optional[dict]) -> Optional[str]:
    if not body:
        return None
    return body.get("errorDescription") or body.get("error") or body.get("message")
