"""Native-async tests for AsyncAgentAuthClient.

No pytest-asyncio is used: each test is a plain ``TestCase`` method that drives the
async client with ``asyncio.run(...)``. The Descope wire layer is mocked at
``httpx.AsyncClient.request`` with ``AsyncMock`` (awaiting it yields each queued
response; queued exceptions raise).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from descope_agent_auth import (
    AsyncAgentAuthClient,
    ClientCredentialsProvider,
    ManagementKeyProvider,
)
from descope_agent_auth.errors import ConnectionAuthorizationRequired

from . import common
from .common import DEFAULT_BASE_URL, PROJECT_ID, make_response, token_obj

CRED = {"access_token": "agent_at", "expires_in": 3600}


def _async_client(credential, **kwargs) -> AsyncAgentAuthClient:
    return AsyncAgentAuthClient(
        project_id=PROJECT_ID,
        base_url=DEFAULT_BASE_URL,
        credential=credential,
        **kwargs,
    )


class TestAsyncClient(common.AgentAuthTest):
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_autonomous_get_token_happy_path(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),  # phase 1: client_credentials acquire
            make_response({"token": token_obj()}),  # phase 2: vault fetch
        ]

        async def scenario():
            client = _async_client(
                ClientCredentialsProvider(client_id="cid", client_secret="s")
            )
            try:
                return await client.connections.get_token(
                    connection="github", identifier="user@example.com"
                )
            finally:
                await client.aclose()

        tok = asyncio.run(scenario())

        self.assertEqual(tok.access_token, "gho_downstream_token")
        _, kwargs = mock_request.call_args  # the exchange (last) call
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:agent_at")

    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_wait_for_connection_returns_once_connected(self, mock_request, _mock_sleep):
        # mgmt key: no phase-1 acquire. poll 1: 404 + connect-url, poll 2: token.
        mock_request.side_effect = [
            make_response({"error": "no"}, status=404),
            make_response({"url": "https://api.descope.com/connect"}),
            make_response({"token": token_obj()}),
        ]
        delivered: list = []

        async def scenario():
            client = _async_client(
                ManagementKeyProvider(management_key="K", allow_management_key=True)
            )
            try:
                return await client.connections.wait_for_connection(
                    connection="github",
                    identifier="u@x.com",
                    on_connect_url=delivered.append,
                    poll_interval=0.0,
                    timeout=5.0,
                )
            finally:
                await client.aclose()

        tok = asyncio.run(scenario())

        self.assertEqual(tok.access_token, "gho_downstream_token")
        self.assertEqual(delivered, ["https://api.descope.com/connect"])

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_resources_token_exchange(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),  # phase 1
            make_response(  # token-exchange
                {"access_token": "resource_at", "token_type": "Bearer", "expires_in": 3600}
            ),
        ]

        async def scenario():
            client = _async_client(
                ClientCredentialsProvider(client_id="cid", client_secret="s")
            )
            try:
                return await client.resources.get_token(resource="urn:my-api")
            finally:
                await client.aclose()

        tok = asyncio.run(scenario())

        self.assertEqual(tok.access_token, "resource_at")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["subject_token"], "agent_at")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_not_connected_raises(self, mock_request):
        mock_request.side_effect = [
            make_response({"error": "not found"}, status=404),
            make_response({"url": "https://api.descope.com/connect?x=1"}),
        ]

        async def scenario():
            client = _async_client(
                ManagementKeyProvider(management_key="K", allow_management_key=True)
            )
            try:
                await client.connections.get_token(
                    connection="github", identifier="user@example.com"
                )
            finally:
                await client.aclose()

        with self.assertRaises(ConnectionAuthorizationRequired) as ctx:
            asyncio.run(scenario())
        self.assertEqual(ctx.exception.connect_url, "https://api.descope.com/connect?x=1")
