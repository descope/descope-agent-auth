"""Tests for the MCP httpx.Auth integration.

The adapter is a thin wrapper over the async client (the real HTTP / error-mapping
paths are covered by test_exchange.py), so these drive it against a fake client and
assert the Bearer injection, argument forwarding, and consent-error propagation.
Async flows run via ``asyncio.run`` to match the repo's test style.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from descope_agent_auth.errors import ConnectionAuthorizationRequired
from descope_agent_auth.integrations.mcp import connection_auth, resource_auth
from descope_agent_auth.types import ApprovalRequest


def _fake_client(*, conn=None, res=None):
    calls = {"connection": [], "resource": []}

    async def conn_get_token(**kwargs):
        calls["connection"].append(kwargs)
        if conn is not None:
            return await conn(**kwargs)
        return SimpleNamespace(access_token="gh_tok")

    async def res_get_token(**kwargs):
        calls["resource"].append(kwargs)
        if res is not None:
            return await res(**kwargs)
        return SimpleNamespace(access_token="res_at")

    client = SimpleNamespace(
        connections=SimpleNamespace(get_token=conn_get_token),
        resources=SimpleNamespace(get_token=res_get_token),
    )
    return client, calls


def _first_request(auth: httpx.Auth, url="https://mcp.example/") -> httpx.Request:
    async def run() -> httpx.Request:
        gen = auth.async_auth_flow(httpx.Request("POST", url))
        return await gen.__anext__()

    return asyncio.run(run())


def test_connection_auth_injects_bearer():
    client, _ = _fake_client()
    auth = connection_auth(client, connection="github", identifier="user_123")
    request = _first_request(auth)
    assert request.headers["Authorization"] == "Bearer gh_tok"


def test_connection_auth_forwards_arguments():
    client, calls = _fake_client()
    approval = ApprovalRequest(login_hint="user@example.com", binding_message="approve")
    auth = connection_auth(
        client,
        connection="github",
        identifier="user_123",
        scopes=["repo"],
        tenant_id="acme",
        act_as_user_token="user_jwt",
        require_approval=approval,
    )
    _first_request(auth)
    assert calls["connection"][0] == {
        "connection": "github",
        "identifier": "user_123",
        "scopes": ["repo"],
        "tenant_id": "acme",
        "act_as_user_token": "user_jwt",
        "require_approval": approval,
    }


def test_connection_auth_propagates_consent_required():
    async def raises(**kwargs):
        raise ConnectionAuthorizationRequired(
            "connect github",
            connect_url="https://connect.example/github",
            connection="github",
            identifier="user_123",
        )

    client, _ = _fake_client(conn=raises)
    auth = connection_auth(client, connection="github", identifier="user_123")
    with pytest.raises(ConnectionAuthorizationRequired) as exc:
        _first_request(auth)
    assert exc.value.connect_url == "https://connect.example/github"


def test_resource_auth_injects_bearer_and_forwards():
    client, calls = _fake_client()
    auth = resource_auth(
        client,
        resource="urn:my-mcp",
        scopes=["read"],
        audience=["https://mcp.acme.com"],
    )
    request = _first_request(auth)
    assert request.headers["Authorization"] == "Bearer res_at"
    assert calls["resource"][0] == {
        "resource": "urn:my-mcp",
        "scopes": ["read"],
        "audience": ["https://mcp.acme.com"],
        "act_as_user_token": None,
        "require_approval": None,
    }


def test_sync_auth_flow_is_rejected():
    client, _ = _fake_client()
    auth = connection_auth(client, connection="github", identifier="u")
    with pytest.raises(RuntimeError):
        # httpx exposes the sync path via sync_auth_flow; we explicitly disallow it.
        list(auth.sync_auth_flow(httpx.Request("GET", "https://mcp.example/")))
