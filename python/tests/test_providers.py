"""Phase-1 credential provider tests (Descope unittest.mock/TestCase style)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from descope_agent_auth import (
    CibaProvider,
    ClientCredentialsProvider,
    DeviceCodeProvider,
    JwtBearerProvider,
    ManagementKeyProvider,
    MemoryTokenStore,
)
from descope_agent_auth.errors import (
    ApprovalDenied,
    ApprovalTimeout,
    CredentialAcquisitionFailed,
    InvalidAuthorizationDetails,
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

    def _assert_paths(self, mock_request, polls):
        paths = [c.args[1] for c in mock_request.call_args_list]
        self.assertEqual(["/oauth2/v1/apps/bc-authorize"] + ["/oauth2/v1/apps/token"] * polls, paths)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_pending_then_approved(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"error": "authorization_pending"}, status=400),
            make_response({"access_token": "ciba_at", "expires_in": 3600}),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")

        self.assertEqual(self.make_client(provider).get_credential().token, "ciba_at")
        self._assert_paths(mock_request, polls=2)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_denied(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"error": "access_denied"}, status=400),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")

        with self.assertRaises(ApprovalDenied):
            self.make_client(provider).get_credential()
        self._assert_paths(mock_request, polls=1)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_timeout(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"error": "expired_token"}, status=400),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")

        with self.assertRaises(ApprovalTimeout):
            self.make_client(provider).get_credential()
        self._assert_paths(mock_request, polls=1)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_refreshes_on_inbound_apps_token_endpoint(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"access_token": "first", "expires_in": -10, "refresh_token": "r1"}),
            make_response({"access_token": "refreshed", "expires_in": 3600}),
        ]
        client = self.make_client(CibaProvider(client_id="cid", login_hint="user@example.com"))

        self.assertEqual(client.get_credential().token, "first")
        self.assertEqual(client.get_credential().token, "refreshed")
        # The refresh did not start a new CIBA request.
        self._assert_paths(mock_request, polls=2)
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["grant_type"], "refresh_token")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_plain_ciba_parses_scope_and_stays_cached(self, mock_request):
        mock_request.side_effect = [
            self._initiated(),
            make_response({"access_token": "ciba_at", "expires_in": 3600, "scope": "openid"}),
        ]
        client = self.make_client(CibaProvider(client_id="cid", login_hint="user@example.com"))

        cred = client.get_credential()
        client.get_credential()

        self.assertEqual("openid", cred.scope)
        self.assertIsNone(cred.authorization_details)
        self._assert_paths(mock_request, polls=1)


PAYMENT = [{"type": "payment_initiation", "amount": "15.00", "currency": "EUR"}]
BANK = "https://bank.example.com"


@patch("asyncio.sleep", AsyncMock())
class TestCibaRichAuthorization(common.AgentAuthTest):
    @staticmethod
    def _approved(**overrides):
        body = {
            "access_token": "rar_at",
            "expires_in": 3600,
            "refresh_token": "r1",
            "scope": "payments:write",
            "authorization_details": PAYMENT,
        }
        body.update(overrides)
        return make_response(body)

    @staticmethod
    def _approve_payment(client, provider):
        return client._bridge.run(
            provider.authenticate(
                login_hint="user@example.com", resource=BANK, authorization_details=PAYMENT
            )
        )

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_sends_details_and_returns_approved_grant(self, mock_request):
        mock_request.side_effect = [TestCibaProvider._initiated(), self._approved()]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")
        client = self.make_client(provider)

        cred = self._approve_payment(client, provider)

        initiate = mock_request.call_args_list[0]
        self.assertEqual("/oauth2/v1/apps/bc-authorize", initiate.args[1])
        self.assertEqual(BANK, initiate.kwargs["data"]["resource"])
        self.assertEqual(PAYMENT, json.loads(initiate.kwargs["data"]["authorization_details"]))
        self.assertEqual(PAYMENT, cred.authorization_details)
        self.assertEqual("payments:write", cred.scope)
        self.assertEqual("r1", cred.refresh_token)  # a handle to the same grant (RFC 9396 s6)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_each_call_asks_again_and_nothing_is_stored(self, mock_request):
        mock_request.side_effect = [
            TestCibaProvider._initiated(),
            self._approved(),
            TestCibaProvider._initiated(),
            self._approved(),
            TestCibaProvider._initiated(),
            make_response({"access_token": "plain_at", "expires_in": 3600}),
        ]
        store = MemoryTokenStore()
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")
        client = self.make_client(provider, store=store)

        self._approve_payment(client, provider)
        self._approve_payment(client, provider)
        self.assertEqual([], store.list())
        # The provider's own credential is a fresh plain CIBA run, not the RAR grant.
        self.assertEqual("plain_at", client.get_credential().token)

        paths = [c.args[1] for c in mock_request.call_args_list]
        self.assertEqual(3, paths.count("/oauth2/v1/apps/bc-authorize"))

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_empty_details_run_plain_ciba(self, mock_request):
        mock_request.side_effect = [TestCibaProvider._initiated(), self._approved()]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")
        client = self.make_client(provider)

        cred = client._bridge.run(
            provider.authenticate(login_hint="user@example.com", authorization_details=[])
        )

        self.assertNotIn("authorization_details", mock_request.call_args_list[0].kwargs["data"])
        self.assertEqual("r1", cred.refresh_token)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_rejected_details_raise_before_any_approval(self, mock_request):
        reason = "Invalid authorization_details: authorization_details type is not registered on the requested resources"
        mock_request.side_effect = [
            make_response(
                {"error": "invalid_authorization_details", "error_description": reason},
                status=400,
            )
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")
        client = self.make_client(provider)

        with self.assertRaises(InvalidAuthorizationDetails) as caught:
            self._approve_payment(client, provider)

        self.assertEqual(reason, caught.exception.error_description)
        self.assertEqual(reason, str(caught.exception))
        self.assertEqual(1, mock_request.call_count)  # no polling, no approval sent

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_details_not_applied_by_server_raise(self, mock_request):
        mock_request.side_effect = [
            TestCibaProvider._initiated(),
            self._approved(authorization_details=None),
        ]
        provider = CibaProvider(client_id="cid", login_hint="user@example.com")
        client = self.make_client(provider)

        with self.assertRaises(InvalidAuthorizationDetails):
            self._approve_payment(client, provider)


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


class TestJwtBearerProvider(common.AgentAuthTest):
    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_exchanges_assertion_for_credential(self, mock_request):
        mock_request.return_value = make_response({"access_token": "jb_at", "expires_in": 3600})
        client = self.make_client(
            JwtBearerProvider(client_id="cid", assertion="signed.jwt.here", scopes=["openid"])
        )

        cred = client.get_credential()

        self.assertEqual(cred.token, "jb_at")
        _, kwargs = mock_request.call_args
        self.assertEqual(
            kwargs["data"]["grant_type"], "urn:ietf:params:oauth:grant-type:jwt-bearer"
        )
        self.assertEqual(kwargs["data"]["assertion"], "signed.jwt.here")
        self.assertEqual(kwargs["data"]["client_id"], "cid")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_assertion_callable_resolved_each_acquire(self, mock_request):
        mock_request.return_value = make_response({"access_token": "jb_at", "expires_in": 3600})
        client = self.make_client(JwtBearerProvider(client_id="cid", assertion=lambda: "fresh.jwt"))

        client.get_credential()

        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["assertion"], "fresh.jwt")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_failure_raises(self, mock_request):
        mock_request.return_value = make_response({"error": "invalid_grant"}, status=400)
        client = self.make_client(JwtBearerProvider(client_id="cid", assertion="bad"))

        with self.assertRaises(CredentialAcquisitionFailed):
            client.get_credential()
