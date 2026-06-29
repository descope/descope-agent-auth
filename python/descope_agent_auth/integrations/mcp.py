"""MCP integration: feed Descope-vaulted tokens into an MCP client's HTTP auth.

The MCP Python client connects to a remote MCP server over an ``httpx``-based
transport. Rather than have the client run the whole OAuth dance itself (discovery,
DCR, the authorization-code redirect, storage, refresh), a *brokered* setup lets
Descope hold and refresh that token in the vault -- and this module hands the
transport an ``httpx.Auth`` that injects the vaulted token as a ``Bearer`` header.

An ``httpx.Auth`` is the portable integration point: the MCP transport accepts one
directly (``auth=``) on releases that expose it, and on newer ones you set it on the
``httpx.AsyncClient`` you pass in -- either way the same object works::

    from mcp.client.streamable_http import streamablehttp_client  # released API
    from descope_agent_auth import AsyncAgentAuthClient
    from descope_agent_auth.integrations.mcp import connection_auth

    auth = connection_auth(client, connection="linear", identifier=user_id)
    async with streamablehttp_client("https://mcp.linear.app", auth=auth) as (r, w, _):
        ...

When the user hasn't connected the provider yet, the token fetch raises
``ConnectionAuthorizationRequired`` (carrying ``connect_url``); it propagates out of
the request so you can catch it where you drive the agent and send the user to
consent, exactly as with a direct ``connections.get_token`` call.

Two flavors, matching the two token types:
  - :func:`connection_auth` -- the MCP server is protected by a provider you've set
    up as a Descope Connection (the token is that provider's own token).
  - :func:`resource_auth` -- the MCP server treats Descope as its OAuth authorization
    server (the token is a Descope-minted Resource token).

This module depends only on ``httpx`` (already a core dependency); it never imports
the MCP SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator, Awaitable, Callable, Generator, List, Optional

import httpx

if TYPE_CHECKING:
    from ..client import AsyncAgentAuthClient

_TokenFetcher = Callable[[], Awaitable[str]]


class _BearerInjectingAuth(httpx.Auth):
    """An ``httpx.Auth`` that fetches a Descope-vaulted token per request and sends
    it as ``Authorization: Bearer ...``. Async-only -- the MCP client is async."""

    requires_request_body = False
    requires_response_body = False

    def __init__(self, fetch: _TokenFetcher) -> None:
        self._fetch = fetch

    def sync_auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        raise RuntimeError(
            "Descope MCP auth is async-only; use an async MCP client / httpx.AsyncClient."
        )

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        # The token fetch is cached + refreshed inside Descope, so per-request calls
        # are cheap. ConnectionAuthorizationRequired (consent needed) propagates here.
        token = await self._fetch()
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


def connection_auth(
    client: "AsyncAgentAuthClient",
    *,
    connection: str,
    identifier: str,
    scopes: Optional[List[str]] = None,
    tenant_id: Optional[str] = None,
    act_as_user_token: Optional[str] = None,
) -> httpx.Auth:
    """Build an ``httpx.Auth`` that injects a Descope **Connection** token (the
    provider's own OAuth token) for ``identifier`` on each MCP request.

    ``identifier`` is the user the agent acts for -- resolve it server-side, never
    from model input.
    """

    async def fetch() -> str:
        token = await client.connections.get_token(
            connection=connection,
            identifier=identifier,
            scopes=scopes,
            tenant_id=tenant_id,
            act_as_user_token=act_as_user_token,
        )
        return token.access_token

    return _BearerInjectingAuth(fetch)


def resource_auth(
    client: "AsyncAgentAuthClient",
    *,
    resource: str,
    scopes: Optional[List[str]] = None,
    audience: Optional[List[str]] = None,
    act_as_user_token: Optional[str] = None,
) -> httpx.Auth:
    """Build an ``httpx.Auth`` that injects a Descope-minted **Resource** token (for
    an MCP server that uses Descope as its OAuth authorization server)."""

    async def fetch() -> str:
        token = await client.resources.get_token(
            resource=resource,
            scopes=scopes,
            audience=audience,
            act_as_user_token=act_as_user_token,
        )
        return token.access_token

    return _BearerInjectingAuth(fetch)
