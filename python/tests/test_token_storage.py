"""Phase-1 credential persistence + refresh (storage in the TokenStore)."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from descope_agent_auth import (
    AgentAuthClient,
    CibaProvider,
    ClientCredentialsProvider,
    DeviceCodeProvider,
    ManagementKeyProvider,
    MemoryTokenStore,
)

from . import common
from .common import DEFAULT_BASE_URL, PROJECT_ID, make_response


def _client(credential, store):
    return AgentAuthClient(
        project_id=PROJECT_ID, base_url=DEFAULT_BASE_URL, credential=credential, store=store
    )


class TestCredentialPersistence(common.AgentAuthTest):
    @patch("httpx.Client.request")
    def test_credential_persisted_and_reused_across_instances(self, mock_request):
        # Simulates a restart: a fresh provider/client backed by the same store
        # should load the credential instead of re-acquiring it.
        mock_request.return_value = make_response({"access_token": "agent_at", "expires_in": 3600})
        store = MemoryTokenStore()

        first = _client(ClientCredentialsProvider(client_id="cid", client_secret="s"), store)
        self.assertEqual(first.get_credential().token, "agent_at")

        second = _client(ClientCredentialsProvider(client_id="cid", client_secret="s"), store)
        self.assertEqual(second.get_credential().token, "agent_at")

        # Only the first client hit the token endpoint; the second loaded from store.
        self.assertEqual(mock_request.call_count, 1)
        self.assertIn(f"cred:client_credentials:{PROJECT_ID}:cid", store.list())

    @patch("httpx.Client.request")
    def test_management_key_is_not_persisted(self, mock_request):
        store = MemoryTokenStore()
        client = _client(
            ManagementKeyProvider(management_key="K", allow_management_key=True), store
        )
        client.get_credential()
        self.assertEqual(store.list(), [])  # nothing written for a static key


@patch("time.sleep", lambda *_: None)
class TestRefreshFromStore(common.AgentAuthTest):
    @patch("httpx.Client.request")
    def test_device_refreshes_from_stored_token_without_reauth(self, mock_request):
        # Pre-seed the store with an EXPIRED device credential that has a refresh
        # token (as if persisted before a restart).
        store = MemoryTokenStore()
        store.set(
            f"cred:device:{PROJECT_ID}:cid",
            json.dumps(
                {
                    "token": "old",
                    "kind": "agent_token",
                    "expires_at": time.time() - 100,
                    "refresh_token": "r1",
                }
            ),
        )
        mock_request.return_value = make_response({"access_token": "new", "expires_in": 3600})

        client = _client(DeviceCodeProvider(client_id="cid"), store)
        cred = client.get_credential()

        self.assertEqual(cred.token, "new")
        # Exactly one call: the refresh. The interactive device flow was NOT re-run.
        self.assertEqual(mock_request.call_count, 1)
        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], "/oauth2/v1/token")
        self.assertEqual(kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(kwargs["data"]["client_id"], "cid")  # device refresh needs client_id

    @patch("httpx.Client.request")
    def test_ciba_refresh_includes_client_secret(self, mock_request):
        store = MemoryTokenStore()
        store.set(
            f"cred:ciba:{PROJECT_ID}:cid:user@example.com",
            json.dumps(
                {
                    "token": "old",
                    "kind": "agent_token",
                    "expires_at": time.time() - 100,
                    "refresh_token": "r1",
                }
            ),
        )
        mock_request.return_value = make_response({"access_token": "new", "expires_in": 3600})

        provider = CibaProvider(
            client_id="cid", client_secret="sec", login_hint="user@example.com"
        )
        cred = _client(provider, store).get_credential()

        self.assertEqual(cred.token, "new")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["data"]["grant_type"], "refresh_token")
        self.assertEqual(kwargs["data"]["client_id"], "cid")
        self.assertEqual(kwargs["data"]["client_secret"], "sec")

    @patch("httpx.Client.request")
    def test_rotated_refresh_token_is_persisted(self, mock_request):
        store = MemoryTokenStore()
        key = f"cred:device:{PROJECT_ID}:cid"
        store.set(
            key,
            json.dumps(
                {
                    "token": "old",
                    "kind": "agent_token",
                    "expires_at": time.time() - 100,
                    "refresh_token": "r1",
                }
            ),
        )
        # Refresh returns a rotated refresh token.
        mock_request.return_value = make_response(
            {"access_token": "new", "expires_in": 3600, "refresh_token": "r2"}
        )

        _client(DeviceCodeProvider(client_id="cid"), store).get_credential()

        stored = json.loads(store.get(key))
        self.assertEqual(stored["token"], "new")
        self.assertEqual(stored["refresh_token"], "r2")  # rotation persisted
