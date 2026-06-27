"""Tests for phases 5-7: CIBA approval gate, tool wrapper, execution seam."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from descope_agent_auth import (
    AgentAuthClient,
    ApprovalRequest,
    CibaProvider,
    ManagementKeyProvider,
    ToolRequest,
    with_connection,
)
from descope_agent_auth.errors import (
    AgentAuthError,
    ApprovalDenied,
    ConnectionAuthorizationRequired,
)

from . import common
from .common import DEFAULT_BASE_URL, PROJECT_ID, make_response, token_obj

USER_LATEST = "/v1/mgmt/outbound/app/user/token/latest"


def _mgmt():
    return ManagementKeyProvider(management_key="K", allow_management_key=True)


@patch("asyncio.sleep", AsyncMock())
class TestApprovalGate(common.AgentAuthTest):
    def _client_with_approval(self):
        return AgentAuthClient(
            project_id=PROJECT_ID,
            base_url=DEFAULT_BASE_URL,
            credential=_mgmt(),
            approval=CibaProvider(client_id="cid", login_hint="user@example.com"),
        )

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_approved_then_exchange_proceeds(self, mock_request):
        mock_request.side_effect = [
            make_response({"auth_req_id": "areq", "interval": 1, "expires_in": 60}),  # initiate
            make_response({"access_token": "approval_at", "expires_in": 3600}),  # poll approved
            make_response({"token": token_obj()}),  # exchange
        ]
        client = self._client_with_approval()

        tok = client.connections.get_token(
            connection="github",
            identifier="user@example.com",
            require_approval=ApprovalRequest(
                login_hint="user@example.com", binding_message="Approve repo access"
            ),
        )

        self.assertEqual(tok.access_token, "gho_downstream_token")
        self.assertEqual(mock_request.call_count, 3)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_denied_blocks_exchange(self, mock_request):
        mock_request.side_effect = [
            make_response({"auth_req_id": "areq", "interval": 1, "expires_in": 60}),
            make_response({"error": "access_denied"}, status=400),
        ]
        client = self._client_with_approval()

        with self.assertRaises(ApprovalDenied):
            client.connections.get_token(
                connection="github",
                identifier="user@example.com",
                require_approval=ApprovalRequest(login_hint="user@example.com"),
            )
        # The exchange never ran (only initiate + denied poll).
        self.assertEqual(mock_request.call_count, 2)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_require_approval_without_provider_errors(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self.make_client(_mgmt())  # no approval provider configured

        with self.assertRaises(AgentAuthError):
            client.connections.get_token(
                connection="github",
                identifier="user@example.com",
                require_approval=ApprovalRequest(login_hint="user@example.com"),
            )


class TestToolWrapper(common.AgentAuthTest):
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_injects_scoped_token(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self.make_client(_mgmt())

        @with_connection(client, connection="github", scopes=["repo"])
        def list_repos(token, identifier):
            return f"{identifier}:{token}"

        result = list_repos(identifier="user@example.com")

        self.assertEqual(result, "user@example.com:gho_downstream_token")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_surfaces_reauth_signal(self, mock_request):
        mock_request.side_effect = [
            make_response({"error": "not found"}, status=404),
            make_response({"url": "https://api.descope.com/connect?x=1"}),
        ]
        client = self.make_client(_mgmt())

        @with_connection(client, connection="github", scopes=["repo"])
        def list_repos(token, identifier):  # pragma: no cover - should not run
            return token

        with self.assertRaises(ConnectionAuthorizationRequired) as ctx:
            list_repos(identifier="user@example.com")
        self.assertEqual(ctx.exception.connect_url, "https://api.descope.com/connect?x=1")


class TestExecutionSeam(common.AgentAuthTest):
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_fetch_mode_returns_token(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self.make_client(_mgmt())  # default mode="fetch"

        tok = client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertEqual(tok.access_token, "gho_downstream_token")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_execute_mode_disables_raw_fetch(self, _mock_request):
        client = self.make_client(_mgmt(), mode="execute")

        with self.assertRaises(AgentAuthError):
            client.connections.get_token(connection="github", identifier="user@example.com")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_execute_routes_request_without_returning_token(self, mock_request):
        client = self.make_client(_mgmt(), mode="execute")

        with self.assertRaises(NotImplementedError):
            client.connections.execute(
                request=ToolRequest(method="GET", url="https://api.github.com/user"),
                connection="github",
                identifier="user@example.com",
            )
        # No HTTP exchange was performed (stub raised before any call).
        mock_request.assert_not_called()

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_execute_method_requires_execute_mode(self, _mock_request):
        client = self.make_client(_mgmt())  # fetch mode

        with self.assertRaises(AgentAuthError):
            client.connections.execute(
                request=ToolRequest(method="GET", url="https://api.github.com/user"),
                connection="github",
                identifier="user@example.com",
            )
