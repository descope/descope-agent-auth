"""ConnectionsClient -- the headline phase-2 operation.

Fetch a scoped downstream provider token (GitHub, Slack, ...) from the vault for a
given identity. Omit ``scopes`` to request the Connection's configured defaults;
pass ``scopes`` to override them entirely (the SDK never clamps to a subset -- the
real guardrail is Policies, not the default-scope list).
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

    # Connect-URL config lives under `options` (redirectUrl, scopes, prompt,
    # loginHint, resources, externalIdentifier). The connect URL requests the SAME
    # scopes as the token fetch, so a user who hasn't connected yet consents to
    # exactly what this tool needs; omitting scopes falls back to the Connection's
    # default scopes. connect_options carries any of the other option fields.
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
        "cache_key": _cache_key(connection, identifier, scopes),
        "connection": connection,
        "identifier": identifier,
        "connect_body": connect_body,
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
        """Return a currently-valid downstream token for ``identifier``.

        Pass ``act_as_user_token`` to run this single call as a specific user --
        present that user's Descope access token (from your authorization-code /
        device-code / CIBA login) so the vault fetch is user-scoped, without
        reconfiguring the client.

        ``connect_options`` sets extra fields on the connect URL built when the user
        hasn't connected yet (``prompt``, ``loginHint``, ``resources``,
        ``externalIdentifier``); ``redirect_url`` and the call's ``scopes`` are added
        to it automatically.

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
