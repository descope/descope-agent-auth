"""ConnectionsClient -- the headline phase-2 operation.

Fetch a scoped downstream provider token (GitHub, Slack, ...) from the vault for a
given identity. Omit ``scopes`` to request the Connection's configured defaults;
pass ``scopes`` to override them entirely (the SDK never clamps to a subset -- the
real guardrail is Policies, not the default-scope list).
"""

from __future__ import annotations

from typing import Any, List, Optional

from .._endpoints import (
    OUTBOUND_TENANT_TOKEN,
    OUTBOUND_TENANT_TOKEN_LATEST,
    OUTBOUND_USER_TOKEN,
    OUTBOUND_USER_TOKEN_LATEST,
)
from ..execution import Execution, ToolRequest
from ..types import ApprovalRequest, VaultToken


def _cache_key(
    connection: str, identifier: str, scopes: Optional[List[str]], tenant_id: Optional[str]
) -> str:
    # tenant_id is part of the key: one Connection can hold several user tokens for
    # the same user, one per tenant, and they are NOT interchangeable.
    scope_part = ",".join(sorted(scopes)) if scopes else "<defaults>"
    tenant_part = tenant_id or "<none>"
    return f"vault:user:{connection}:{identifier}:{tenant_part}:{scope_part}"


def _tenant_cache_key(connection: str, tenant_id: str, scopes: Optional[List[str]]) -> str:
    scope_part = ",".join(sorted(scopes)) if scopes else "<defaults>"
    return f"vault:tenant:{connection}:{tenant_id}:{scope_part}"


def _build_args(
    *,
    connection: str,
    identifier: str,
    scopes: Optional[List[str]],
    tenant_id: Optional[str],
    with_refresh_token: bool,
    force_refresh: bool,
    redirect_url: Optional[str],
    connect_options: Optional[dict],
    require_approval: Optional[ApprovalRequest],
    act_as_user_token: Optional[str],
) -> dict:
    body: dict = {"appId": connection, "userId": identifier}
    if tenant_id:
        body["tenantId"] = tenant_id
    if with_refresh_token or force_refresh:
        body["options"] = {"withRefreshToken": with_refresh_token, "forceRefresh": force_refresh}

    # Omitted scopes -> /latest (Connection defaults); explicit scopes -> override.
    if scopes:
        path = OUTBOUND_USER_TOKEN
        body["scopes"] = list(scopes)
    else:
        path = OUTBOUND_USER_TOKEN_LATEST

    # Connect-URL config lives under `options`. The SDK fills in the two documented
    # fields -- `redirectUrl` and `scopes` -- so the connect URL requests the SAME
    # scopes as the token fetch (a user who hasn't connected yet consents to exactly
    # what this tool needs; omitting scopes falls back to the Connection's default
    # scopes). `connect_options` is an escape hatch for any additional provider-
    # specific OAuth passthrough fields; it does NOT bind the URL to a user -- the
    # connection is associated with whoever the request's bearer token identifies.
    options: dict = dict(connect_options or {})
    if redirect_url:
        options["redirectUrl"] = redirect_url
    if scopes:
        options["scopes"] = list(scopes)

    connect_body: dict = {"appId": connection}
    if tenant_id:
        connect_body["tenantId"] = tenant_id
    if options:
        connect_body["options"] = options

    return {
        "path": path,
        "body": body,
        "cache_key": _cache_key(connection, identifier, scopes, tenant_id),
        "connection": connection,
        "identifier": identifier,
        "connect_body": connect_body,
        "force_refresh": force_refresh,
        "require_approval": require_approval,
        "act_as_user_token": act_as_user_token,
    }


def _build_tenant_args(
    *,
    connection: str,
    tenant_id: str,
    scopes: Optional[List[str]],
    with_refresh_token: bool,
    force_refresh: bool,
    require_approval: Optional[ApprovalRequest],
    act_as_user_token: Optional[str],
) -> dict:
    body: dict = {"appId": connection, "tenantId": tenant_id}
    if with_refresh_token or force_refresh:
        body["options"] = {"withRefreshToken": with_refresh_token, "forceRefresh": force_refresh}

    if scopes:
        path = OUTBOUND_TENANT_TOKEN
        body["scopes"] = list(scopes)
    else:
        path = OUTBOUND_TENANT_TOKEN_LATEST

    # No connect_body: a tenant-level Connection token is admin/IaC-provisioned
    # (a shared org credential), not minted by a per-user OAuth consent, so there
    # is no connect URL to build on a miss.
    return {
        "path": path,
        "body": body,
        "cache_key": _tenant_cache_key(connection, tenant_id, scopes),
        "connection": connection,
        "identifier": None,
        "connect_body": None,
        "force_refresh": force_refresh,
        "require_approval": require_approval,
        "act_as_user_token": act_as_user_token,
    }


class ConnectionsClient:
    def __init__(self, execution: Execution) -> None:
        self._execution = execution

    def get_token(
        self,
        *,
        connection: str,
        identifier: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        with_refresh_token: bool = False,
        force_refresh: bool = False,
        redirect_url: Optional[str] = None,
        connect_options: Optional[dict] = None,
        require_approval: Optional[ApprovalRequest] = None,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        """Return a currently-valid **user-level** downstream token for ``identifier``.

        ``tenant_id`` selects *which* of a user's tokens to fetch: a single
        Connection can hold several tokens for the same user, one per tenant. Omit
        ``tenant_id`` to get the user's tenant-less token; pass it to get the token
        bound to that tenant. They are distinct -- asking for a tenant-bound token
        *without* its ``tenant_id`` reads as "not connected" (raises
        ``ConnectionAuthorizationRequired``). For an org-shared token that isn't tied
        to any user, use ``get_tenant_token`` instead.

        Pass ``act_as_user_token`` to run this single call as a specific user --
        present that user's Descope access token (from your authorization-code /
        device-code / CIBA login) so the vault fetch is user-scoped, without
        reconfiguring the client.

        ``connect_options`` is an escape hatch for extra provider-specific
        passthrough fields on the connect URL built when the user hasn't connected
        yet (the SDK adds ``redirect_url`` and the call's ``scopes`` automatically).
        It does **not** bind the URL to a user -- Descope associates the connection
        with whoever the request's bearer token identifies, so a backend with only a
        management key cannot target an arbitrary user this way (see the docs).

        Raises ``ConnectionAuthorizationRequired`` (carrying ``connect_url``) when
        the user hasn't connected the account yet, ``PolicyDenied`` when an agent
        token lacks policy permission, ``ApprovalDenied`` / ``ApprovalTimeout`` if a
        ``require_approval`` gate fails, or ``TokenExchangeFailed`` otherwise.
        """
        args = _build_args(
            connection=connection,
            identifier=identifier,
            scopes=scopes,
            tenant_id=tenant_id,
            with_refresh_token=with_refresh_token,
            force_refresh=force_refresh,
            redirect_url=redirect_url,
            connect_options=connect_options,
            require_approval=require_approval,
            act_as_user_token=act_as_user_token,
        )
        return self._execution.fetch_token(**args)

    def get_tenant_token(
        self,
        *,
        connection: str,
        tenant_id: str,
        scopes: Optional[List[str]] = None,
        with_refresh_token: bool = False,
        force_refresh: bool = False,
        require_approval: Optional[ApprovalRequest] = None,
        act_as_user_token: Optional[str] = None,
    ) -> VaultToken:
        """Return a currently-valid **tenant-level** downstream token.

        A tenant-level Connection token is a single credential shared by a whole
        tenant/organization (e.g. an org API key, or an org-wide OAuth token), keyed
        by ``tenant_id`` with no user. Because it isn't tied to a user, this is the
        one Connection fetch an **autonomous agent** (client-credentials, no user
        token) can perform -- provided its identity is associated with the tenant.

        Unlike ``get_token`` there is no connect-URL fallback: a tenant token is
        provisioned by an admin / IaC, not by a per-user OAuth consent. A miss raises
        ``ConnectionAuthorizationRequired`` with no ``connect_url``.
        """
        args = _build_tenant_args(
            connection=connection,
            tenant_id=tenant_id,
            scopes=scopes,
            with_refresh_token=with_refresh_token,
            force_refresh=force_refresh,
            require_approval=require_approval,
            act_as_user_token=act_as_user_token,
        )
        return self._execution.fetch_token(**args)

    def execute(
        self,
        *,
        request: ToolRequest,
        connection: str,
        identifier: str,
        scopes: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        connect_options: Optional[dict] = None,
        require_approval: Optional[ApprovalRequest] = None,
        act_as_user_token: Optional[str] = None,
    ) -> Any:
        """Execute-mode counterpart of ``get_token`` (see execution seam).

        Routes ``request`` through Descope's hosted execution endpoint with the
        token kept vaulted. Stubbed until that endpoint ships; requires
        ``mode="execute"``.
        """
        args = _build_args(
            connection=connection,
            identifier=identifier,
            scopes=scopes,
            tenant_id=tenant_id,
            with_refresh_token=False,
            force_refresh=False,
            redirect_url=None,
            connect_options=connect_options,
            require_approval=require_approval,
            act_as_user_token=act_as_user_token,
        )
        return self._execution.execute(request=request, **args)
