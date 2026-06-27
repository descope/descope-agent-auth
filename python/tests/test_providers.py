"""Phase-1 credential provider tests (Descope unittest.mock/TestCase style)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from descope_agent_auth import (
    CibaProvider,
    ClientCredentialsProvider,
    DeviceCodeProvider,
    ManagementKeyProvider,
)
from descope_agent_auth.errors import (
    ApprovalDenied,
    ApprovalTimeout,
    CredentialAcquisitionFailed,
)

from . import common
from .common import make_response


class TestClientCredentialsProvider(common.AgentAuthTest):
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_happy_path_uses_basic_auth(self, mock_request):
        mock_request.return_value = make_response({"access_token": "agent_at", "expires_in": 3600})
        client = self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

        cred = client.get_credential()

        self.assertEqual(cred.token, "agent_at")
        self.assertFalse(cred.is_privileged)
        self.assertFalse(cred.is_expired())
        # Authorization header is HTTP Basic.
        _, kwargs = mock_request.call_args
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("Basic "))

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_caches_until_expiry(self, mock_request):
        mock_request.return_value = make_response({"access_token": "agent_at", "expires_in": 3600})
        client = self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

        client.get_credential()
        client.get_credential()

        self.assertEqual(mock_request.call_count, 1)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_acquisition_failure(self, mock_request):
        mock_request.return_value = make_response({"error": "invalid_client"}, status=401)
        client = self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="bad"))

        with self.assertRaises(CredentialAcquisitionFailed):
            client.get_credential()

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_reacquires_when_expired(self, mock_request):
        mock_request.side_effect = [
            make_response({"access_token": "first", "expires_in": -10}),
            make_response({"access_token": "second", "expires_in": 3600}),
        ]
        client = self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

        self.assertEqual(client.get_credential().token, "first")
        self.assertEqual(client.get_credential().token, "second")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_uses_refresh_token_grant_when_held(self, mock_request):
        mock_request.side_effect = [
            make_response({"access_token": "first", "expires_in": -10, "refresh_token": "r1"}),
            make_response({"access_token": "refreshed", "expires_in": 3600}),
        ]
        client = self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

        self.assertEqual(client.get_credential().token, "first")
        self.assertEqual(client.get_credential().token, "refreshed")
        # Second call used the refresh_token grant.
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["grant_type"], "refresh_token")


@patch("asyncio.sleep", AsyncMock())
class TestDeviceCodeProvider(common.AgentAuthTest):
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_pending_then_success(self, mock_request):
        mock_request.side_effect = [
            make_response(
                {
                    "device_code": "dev123",
                    "user_code": "WXYZ-1234",
                    "verification_uri": "https://verify",
                    "interval": 1,
                    "expires_in": 60,
                }
            ),
            make_response({"error": "authorization_pending"}, status=400),
            make_response({"access_token": "device_at", "expires_in": 3600}),
        ]
        seen = {}
        provider = DeviceCodeProvider(
            client_id="cid", on_pending=lambda p: seen.update(code=p.user_code)
        )

        cred = self.make_client(provider).get_credential()

        self.assertEqual(cred.token, "device_at")
        self.assertEqual(seen["code"], "WXYZ-1234")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_timeout(self, mock_request):
        mock_request.return_value = make_response(
            {"device_code": "d", "interval": 1, "expires_in": 0}
        )
        provider = DeviceCodeProvider(client_id="cid", max_wait_seconds=0)

        with self.assertRaises(CredentialAcquisitionFailed):
            self.make_client(provider).get_credential()


@patch("asyncio.sleep", AsyncMock())
class TestCibaProvider(common.AgentAuthTest):
    @staticmethod
    def _initiated():
        return make_response({"auth_req_id": "areq", "interval": 1, "expires_in": 60})

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_pending_then_approved(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"error": "authorization_pending"}, status=400),
            make_response({"access_token": "ciba_at", "expires_in": 3600}),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")

        self.assertEqual(self.make_client(provider).get_credential().token, "ciba_at")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_denied(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"error": "access_denied"}, status=400),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")

        with self.assertRaises(ApprovalDenied):
            self.make_client(provider).get_credential()

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_timeout(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"error": "expired_token"}, status=400),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")

        with self.assertRaises(ApprovalTimeout):
            self.make_client(provider).get_credential()


class TestManagementKeyProvider(common.AgentAuthTest):
    def test_requires_explicit_optin(self):
        with self.assertRaises(CredentialAcquisitionFailed):
            ManagementKeyProvider(management_key="K123")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_is_privileged(self, _mock_request):
        provider = ManagementKeyProvider(management_key="K123", allow_management_key=True)
        client = self.make_client(provider)

        cred = client.get_credential()

        self.assertEqual(cred.token, "K123")
        self.assertTrue(cred.is_privileged)
