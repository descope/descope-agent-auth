"""ConnectionsClient -- the headline phase-2 operation.

Fetch a scoped downstream provider token (GitHub, Slack, ...) from the vault for a
given identity. Omit ``scopes`` to request the Connection's configured defaults;
pass ``scopes`` to override them entirely (the SDK never clamps to a subset -- the
real guardrail is Connection Policies, not the default-scope list).
"""

from __future__ import annotations

from typing import Any, List, Optional

from .._endpoints import OUTBOUND_USER_TOKEN, OUTBOUND_USER_TOKEN_LATEST
from ..execution import Execution, ToolRequest
from ..types import ApprovalRequest, VaultToken


def _cache_key(connection: str, identifier: str, scopes: Optional[List[str]]) -> str:
    scope_part = ",".join(sorted(scopes)) if scopes else "<defaults>"
    return f"vault:user:{connection}:{identifier}:{scope_part}"


def _build_args(
    *,
    connection: str,
    identifier: str,
    scopes: Optional[List[str]],
    tenant_id: Optional[str],
    with_refresh_token: bool,
    force_refresh: bool,
    redirect_url: Optional[str],
    require_approval: Optional[ApprovalRequest],
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

    connect_body: dict = {"appId": connection}
    if tenant_id:
        connect_body["tenantId"] = tenant_id
    if scopes:
        connect_body["scopes"] = list(scopes)
    if redirect_url:
        connect_body["options"] = {"redirectUrl": redirect_url}

    return {
        "path": path,
        "body": body,
        "cache_key": _cache_key(connection, identifier, scopes),
        "connection": connection,
        "identifier": identifier,
        "connect_body": connect_body,
        "force_refresh": force_refresh,
        "require_approval": require_approval,
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
        require_approval: Optional[ApprovalRequest] = None,
    ) -> VaultToken:
        """Return a currently-valid downstream token for ``identifier``.

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
            require_approval=require_approval,
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
        require_approval: Optional[ApprovalRequest] = None,
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
            require_approval=require_approval,
        )
        return self._execution.execute(request=request, **args)
