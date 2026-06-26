"""User-scoped access: AccessTokenProvider + per-call act_as_user_token override."""

from __future__ import annotations

from unittest.mock import patch

from descope_agent_auth import (
    AccessTokenProvider,
    ClientCredentialsProvider,
)

from . import common
from .common import PROJECT_ID, make_response, token_obj

USER_LATEST = "/v1/mgmt/outbound/app/user/token/latest"
TOKEN_URL = "/oauth2/v1/token"
CRED = {"access_token": "agent_at", "expires_in": 3600}


class TestAccessTokenProvider(common.AgentAuthTest):
    @patch("httpx.Client.request")
    def test_wraps_a_supplied_token_without_acquiring(self, mock_request):
        # No acquisition call should be made; the supplied token is used directly.
        client = self.make_client(AccessTokenProvider(access_token="user_jwt"))

        cred = client.get_credential()

        self.assertEqual(cred.token, "user_jwt")
        self.assertFalse(cred.is_privileged)
        mock_request.assert_not_called()

    @patch("httpx.Client.request")
    def test_connection_fetch_is_user_scoped(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self.make_client(AccessTokenProvider(access_token="user_jwt"))

        client.connections.get_token(connection="github", identifier="user@example.com")

        _, kwargs = mock_request.call_args
        # The user's token is the bearer -> user-scoped vault fetch.
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:user_jwt")

    @patch("httpx.Client.request")
    def test_resource_token_exchange_uses_user_subject(self, mock_request):
        mock_request.return_value = make_response(
            {"access_token": "resource_at", "expires_in": 3600, "scope": "read"}
        )
        client = self.make_client(AccessTokenProvider(access_token="user_jwt"))

        tok = client.resources.get_token(resource="urn:my-api", scopes=["read"])

        self.assertEqual(tok.access_token, "resource_at")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["subject_token"], "user_jwt")


class TestActAsUserTokenOverride(common.AgentAuthTest):
    """One shared autonomous client serving many users via per-call user tokens."""

    def _agent_client(self):
        return self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

    @patch("httpx.Client.request")
    def test_connection_override_uses_user_token_as_bearer(self, mock_request):
        # The override supplies the credential, so no phase-1 acquisition happens:
        # the single call is the exchange, authed with the user's token.
        mock_request.return_value = make_response({"token": token_obj()})
        client = self._agent_client()

        client.connections.get_token(
            connection="github",
            identifier="user@example.com",
            act_as_user_token="user_jwt",
        )

        self.assertEqual(mock_request.call_count, 1)
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:user_jwt")

    @patch("httpx.Client.request")
    def test_resource_override_sets_user_subject_token(self, mock_request):
        mock_request.return_value = make_response(
            {"access_token": "resource_at", "expires_in": 3600}
        )
        client = self._agent_client()

        client.resources.get_token(resource="urn:my-api", act_as_user_token="user_jwt")

        self.assertEqual(mock_request.call_count, 1)
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["subject_token"], "user_jwt")

    @patch("httpx.Client.request")
    def test_override_works_even_when_client_has_no_user_context(self, mock_request):
        # Without the override the client-credentials token would be the bearer.
        mock_request.side_effect = [make_response(CRED), make_response({"token": token_obj()})]
        client = self._agent_client()

        client.connections.get_token(connection="github", identifier="user@example.com")

        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:agent_at")
