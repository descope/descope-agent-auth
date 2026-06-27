"""Phase-2 vault exchange tests (Descope unittest.mock/TestCase style)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from descope_agent_auth import (
    ClientCredentialsProvider,
    ManagementKeyProvider,
)
from descope_agent_auth.errors import (
    AgentAuthError,
    ConnectionAuthorizationRequired,
    PolicyDenied,
    TokenExchangeFailed,
)

from . import common
from .common import PROJECT_ID, make_response, token_obj

USER_LATEST = "/v1/mgmt/outbound/app/user/token/latest"
USER_SCOPED = "/v1/mgmt/outbound/app/user/token"
TENANT_LATEST = "/v1/mgmt/outbound/app/tenant/token/latest"
TENANT_SCOPED = "/v1/mgmt/outbound/app/tenant/token"
CONNECT = "/v1/mgmt/outbound/app/connect"

CRED = {"access_token": "agent_at", "expires_in": 3600}


@patch("asyncio.sleep", AsyncMock())
class TestConnectionsExchange(common.AgentAuthTest):
    def _agent_client(self):
        return self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

    def _mgmt_client(self):
        return self.make_client(
            ManagementKeyProvider(management_key="K123", allow_management_key=True)
        )

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_omitted_scopes_hits_latest_with_agent_bearer(self, mock_request):
        mock_request.side_effect = [make_response(CRED), make_response({"token": token_obj()})]
        client = self._agent_client()

        tok = client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(tok.access_token, "gho_downstream_token")
        args, kwargs = mock_request.call_args  # the exchange (last) call
        self.assertEqual(args[1], USER_LATEST)
        self.assertNotIn("scopes", kwargs["json"])
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:agent_at")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_explicit_scopes_override_hits_scoped_endpoint(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"token": token_obj(scopes=["repo", "read:org"])}),
        ]
        client = self._agent_client()

        tok = client.connections.get_token(
            connection="github", identifier="user@example.com", scopes=["repo", "read:org"]
        )

        self.assertEqual(tok.scopes, ["repo", "read:org"])
        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], USER_SCOPED)
        self.assertEqual(kwargs["json"]["scopes"], ["repo", "read:org"])

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_not_connected_raises_with_connect_url(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "not found"}, status=404),
            make_response({"url": "https://api.descope.com/connect?x=1"}),
        ]
        client = self._agent_client()

        with self.assertRaises(ConnectionAuthorizationRequired) as ctx:
            client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(ctx.exception.connect_url, "https://api.descope.com/connect?x=1")
        self.assertEqual(ctx.exception.connection, "github")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_connect_url_carries_scopes_and_options(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),  # phase 1
            make_response({"error": "no"}, status=404),  # scoped fetch -> not connected
            make_response({"url": "https://api.descope.com/connect"}),  # connect
        ]
        client = self._agent_client()

        with self.assertRaises(ConnectionAuthorizationRequired):
            client.connections.get_token(
                connection="github",
                identifier="user@example.com",
                scopes=["repo"],
                redirect_url="https://app/cb",
                connect_options={"prompt": ["consent"]},
            )

        # The connect call is the last request; its JSON body nests everything in options.
        _, kwargs = mock_request.call_args
        opts = kwargs["json"]["options"]
        self.assertEqual(opts["scopes"], ["repo"])
        self.assertEqual(opts["redirectUrl"], "https://app/cb")
        self.assertEqual(opts["prompt"], ["consent"])
        self.assertNotIn("scopes", kwargs["json"])  # not at top level

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_policy_denied(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "policy denied"}, status=403),
        ]
        client = self._agent_client()

        with self.assertRaises(PolicyDenied):
            client.connections.get_token(connection="github", identifier="user@example.com")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_generic_failure(self, mock_request):
        # 500 is retried up to 3 times by the HTTP layer.
        mock_request.side_effect = [make_response(CRED)] + [
            make_response({"error": "boom"}, status=500) for _ in range(3)
        ]
        client = self._agent_client()

        with self.assertRaises(TokenExchangeFailed):
            client.connections.get_token(connection="github", identifier="user@example.com")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_management_key_unrestricted_exchange(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self._mgmt_client()

        tok = client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(tok.access_token, "gho_downstream_token")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:K123")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_downstream_token_cached(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self._mgmt_client()

        client.connections.get_token(connection="github", identifier="user@example.com")
        client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(mock_request.call_count, 1)  # second served from cache

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_cache_disabled_fetches_every_time(self, mock_request):
        # cache_tokens=False -> no cache read/write, so Policies are re-enforced on
        # every call (each fetch hits Descope).
        mock_request.return_value = make_response({"token": token_obj()})
        client = self.make_client(
            ManagementKeyProvider(management_key="K123", allow_management_key=True),
            cache_tokens=False,
        )

        client.connections.get_token(connection="github", identifier="user@example.com")
        client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(mock_request.call_count, 2)  # not cached

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_user_token_threads_tenant_id_into_body(self, mock_request):
        mock_request.side_effect = [make_response(CRED), make_response({"token": token_obj()})]
        client = self._agent_client()

        client.connections.get_token(
            connection="github", identifier="user@example.com", tenant_id="t1"
        )

        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["json"]["tenantId"], "t1")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_same_user_different_tenant_not_cache_collision(self, mock_request):
        # A user can hold one token per tenant for the same Connection; the two must
        # not collide in cache. Each distinct tenant_id hits the network.
        mock_request.side_effect = [
            make_response({"token": token_obj()}),
            make_response({"token": token_obj()}),
        ]
        client = self._mgmt_client()  # mgmt key: no phase-1 acquire call

        client.connections.get_token(connection="github", identifier="u@x.com", tenant_id="t1")
        client.connections.get_token(connection="github", identifier="u@x.com", tenant_id="t2")

        self.assertEqual(mock_request.call_count, 2)  # not served from cache

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_tenant_token_latest(self, mock_request):
        mock_request.side_effect = [make_response(CRED), make_response({"token": token_obj()})]
        client = self._agent_client()  # autonomous agent: tenant tokens need no user

        tok = client.connections.get_tenant_token(connection="github", tenant_id="t1")

        self.assertEqual(tok.access_token, "gho_downstream_token")
        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], TENANT_LATEST)
        self.assertEqual(kwargs["json"]["tenantId"], "t1")
        self.assertNotIn("userId", kwargs["json"])

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_tenant_token_scoped(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"token": token_obj(scopes=["read"])}),
        ]
        client = self._agent_client()

        client.connections.get_tenant_token(
            connection="github", tenant_id="t1", scopes=["read"]
        )

        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], TENANT_SCOPED)
        self.assertEqual(kwargs["json"]["scopes"], ["read"])

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_tenant_token_miss_raises_without_connect_url(self, mock_request):
        # Tenant tokens are admin-provisioned: a miss has no connect URL, and the
        # SDK must NOT attempt a connect call.
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "not found"}, status=404),
        ]
        client = self._agent_client()

        with self.assertRaises(ConnectionAuthorizationRequired) as ctx:
            client.connections.get_tenant_token(connection="github", tenant_id="t1")

        self.assertIsNone(ctx.exception.connect_url)
        self.assertEqual(mock_request.call_count, 2)  # no third (connect) call

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_wait_for_connection_returns_once_connected(self, mock_request):
        # phase 1, then poll 1: 404 + connect-url (not connected), then poll 2: token.
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "no"}, status=404),
            make_response({"url": "https://api.descope.com/connect"}),
            make_response({"token": token_obj()}),
        ]
        client = self._agent_client()
        delivered: list = []

        tok = client.connections.wait_for_connection(
            connection="github",
            identifier="u@x.com",
            on_connect_url=delivered.append,
            poll_interval=0.0,
            timeout=5.0,
        )

        self.assertEqual(tok.access_token, "gho_downstream_token")
        self.assertEqual(delivered, ["https://api.descope.com/connect"])  # delivered once

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_wait_for_connection_times_out(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "no"}, status=404),
            make_response({"url": "https://api.descope.com/connect"}),
        ]
        client = self._agent_client()

        with self.assertRaises(AgentAuthError):
            client.connections.wait_for_connection(
                connection="github", identifier="u@x.com", timeout=0.0
            )


@patch("asyncio.sleep", AsyncMock())
class TestResourcesExchange(common.AgentAuthTest):
    """Resource tokens are minted via the RFC 8693 token-exchange grant."""

    def _agent_client(self):
        return self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_token_exchange_returns_resource_token(self, mock_request):
        mock_request.side_effect = [
            make_response({"access_token": "agent_at", "expires_in": 3600}),  # phase 1
            make_response(  # token-exchange
                {
                    "access_token": "resource_at",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "read",
                }
            ),
        ]
        client = self._agent_client()

        tok = client.resources.get_token(resource="urn:my-api", scopes=["read"])

        self.assertEqual(tok.access_token, "resource_at")
        self.assertEqual(tok.scopes, ["read"])
        args, kwargs = mock_request.call_args  # the token-exchange call
        self.assertEqual(args[1], "/oauth2/v1/token")
        self.assertEqual(
            kwargs["data"]["grant_type"], "urn:ietf:params:oauth:grant-type:token-exchange"
        )
        self.assertEqual(kwargs["data"]["resource"], "urn:my-api")
        self.assertEqual(kwargs["data"]["subject_token"], "agent_at")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_management_key_rejected_for_resources(self, mock_request):
        client = self.make_client(
            ManagementKeyProvider(management_key="K", allow_management_key=True)
        )
        with self.assertRaises(AgentAuthError):
            client.resources.get_token(resource="urn:my-api")
        mock_request.assert_not_called()  # token-exchange never attempted

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_policy_denied(self, mock_request):
        mock_request.side_effect = [
            make_response({"access_token": "agent_at", "expires_in": 3600}),
            make_response({"error": "access_denied"}, status=403),
        ]
        client = self._agent_client()
        with self.assertRaises(PolicyDenied):
            client.resources.get_token(resource="urn:my-api")
