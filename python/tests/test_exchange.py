"""Phase-2 vault exchange tests (Descope unittest.mock/TestCase style)."""

from __future__ import annotations

from unittest.mock import patch

from descope_agent_auth import (
    ClientCredentialsProvider,
    ManagementKeyProvider,
)
from descope_agent_auth.errors import (
    ConnectionAuthorizationRequired,
    PolicyDenied,
    TokenExchangeFailed,
)

from . import common
from .common import PROJECT_ID, make_response, token_obj

USER_LATEST = "/v1/mgmt/outbound/app/user/token/latest"
USER_SCOPED = "/v1/mgmt/outbound/app/user/token"
CONNECT = "/v1/mgmt/outbound/app/connect"

CRED = {"access_token": "agent_at", "expires_in": 3600}


@patch("time.sleep", lambda *_: None)
class TestConnectionsExchange(common.AgentAuthTest):
    def _agent_client(self):
        return self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

    def _mgmt_client(self):
        return self.make_client(
            ManagementKeyProvider(management_key="K123", allow_management_key=True)
        )

    @patch("httpx.Client.request")
    def test_omitted_scopes_hits_latest_with_agent_bearer(self, mock_request):
        mock_request.side_effect = [make_response(CRED), make_response({"token": token_obj()})]
        client = self._agent_client()

        tok = client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(tok.access_token, "gho_downstream_token")
        args, kwargs = mock_request.call_args  # the exchange (last) call
        self.assertEqual(args[1], USER_LATEST)
        self.assertNotIn("scopes", kwargs["json"])
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:agent_at")

    @patch("httpx.Client.request")
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

    @patch("httpx.Client.request")
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

    @patch("httpx.Client.request")
    def test_policy_denied(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "policy denied"}, status=403),
        ]
        client = self._agent_client()

        with self.assertRaises(PolicyDenied):
            client.connections.get_token(connection="github", identifier="user@example.com")

    @patch("httpx.Client.request")
    def test_generic_failure(self, mock_request):
        # 500 is retried up to 3 times by the HTTP layer.
        mock_request.side_effect = [make_response(CRED)] + [
            make_response({"error": "boom"}, status=500) for _ in range(3)
        ]
        client = self._agent_client()

        with self.assertRaises(TokenExchangeFailed):
            client.connections.get_token(connection="github", identifier="user@example.com")

    @patch("httpx.Client.request")
    def test_management_key_unrestricted_exchange(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self._mgmt_client()

        tok = client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(tok.access_token, "gho_downstream_token")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:K123")

    @patch("httpx.Client.request")
    def test_downstream_token_cached(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self._mgmt_client()

        client.connections.get_token(connection="github", identifier="user@example.com")
        client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(mock_request.call_count, 1)  # second served from cache


@patch("time.sleep", lambda *_: None)
class TestResourcesExchange(common.AgentAuthTest):
    def _mgmt_client(self):
        return self.make_client(
            ManagementKeyProvider(management_key="K", allow_management_key=True)
        )

    @patch("httpx.Client.request")
    def test_omitted_scopes_hits_tenant_latest(self, mock_request):
        mock_request.return_value = make_response(
            {"token": token_obj(appId="urn:res", scopes=["read"])}
        )
        client = self._mgmt_client()

        tok = client.resources.get_token(resource="urn:res")

        self.assertEqual(tok.scopes, ["read"])
        args, _ = mock_request.call_args
        self.assertEqual(args[1], "/v1/mgmt/outbound/app/tenant/token/latest")

    @patch("httpx.Client.request")
    def test_explicit_scopes_hits_tenant_scoped(self, mock_request):
        mock_request.return_value = make_response(
            {"token": token_obj(appId="urn:res", scopes=["read", "write"])}
        )
        client = self._mgmt_client()

        tok = client.resources.get_token(
            resource="urn:res", scopes=["read", "write"], tenant_id="t1"
        )

        self.assertEqual(tok.scopes, ["read", "write"])
        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], "/v1/mgmt/outbound/app/tenant/token")
        self.assertEqual(kwargs["json"]["scopes"], ["read", "write"])
        self.assertEqual(kwargs["json"]["tenantId"], "t1")
