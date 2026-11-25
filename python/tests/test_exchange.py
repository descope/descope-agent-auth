"""Phase-2 vault exchange tests (Descope unittest.mock/TestCase style)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from descope_agent_auth import (
    AgentAuthClient,
    AccessTokenProvider,
    CibaProvider,
    ClientCredentialsProvider,
    ManagementKeyProvider,
)
from descope_agent_auth.errors import (
    AgentAuthError,
    ConnectionAuthorizationRequired,
    ConnectUrlFailed,
    CredentialAcquisitionFailed,
    PolicyDenied,
    TokenExchangeFailed,
)

from descope_agent_auth.store.memory import MemoryTokenStore

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

    # -- cache scoping (descope/etc#17066): a cached Connection token must only be
    # served to the caller that fetched it, never to another user or agent client
    # that shares the client or the TokenStore.

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_cache_not_shared_between_acting_users(self, mock_request):
        mock_request.side_effect = [
            make_response({"token": token_obj(accessToken="token-for-A")}),
            make_response({"token": token_obj(accessToken="token-for-B")}),
        ]
        client = self._mgmt_client()

        a = client.connections.get_token(
            connection="github", identifier="u@x.com", act_as_user_token="user-A-jwt"
        )
        b = client.connections.get_token(
            connection="github", identifier="u@x.com", act_as_user_token="user-B-jwt"
        )

        self.assertEqual(a.access_token, "token-for-A")
        self.assertEqual(b.access_token, "token-for-B")
        _, kwargs = mock_request.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {PROJECT_ID}:user-B-jwt")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_same_acting_user_is_still_cached(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        client = self._mgmt_client()

        for _ in range(2):
            client.connections.get_token(
                connection="github", identifier="u@x.com", act_as_user_token="user-A-jwt"
            )

        self.assertEqual(mock_request.call_count, 1)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_cache_not_shared_between_agent_clients_on_one_store(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"token": token_obj(accessToken="token-via-agent-1")}),
            make_response(CRED),
            make_response({"token": token_obj(accessToken="token-via-agent-2")}),
        ]
        store = MemoryTokenStore()
        one = self.make_client(
            ClientCredentialsProvider(client_id="cid1", client_secret="s"), store=store
        )
        two = self.make_client(
            ClientCredentialsProvider(client_id="cid2", client_secret="s"), store=store
        )

        one.connections.get_token(connection="github", identifier="u@x.com")
        tok = two.connections.get_token(connection="github", identifier="u@x.com")

        self.assertEqual(tok.access_token, "token-via-agent-2")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_cache_not_shared_between_projects_on_one_store(self, mock_request):
        mock_request.side_effect = [
            make_response({"token": token_obj(accessToken="token-in-P1")}),
            make_response({"token": token_obj(accessToken="token-in-P2")}),
        ]
        store = MemoryTokenStore()
        mgmt = dict(management_key="K123", allow_management_key=True)
        p1 = AgentAuthClient(
            project_id="P1",
            base_url=common.DEFAULT_BASE_URL,
            credential=ManagementKeyProvider(**mgmt),
            store=store,
        )
        p2 = AgentAuthClient(
            project_id="P2",
            base_url=common.DEFAULT_BASE_URL,
            credential=ManagementKeyProvider(**mgmt),
            store=store,
        )

        p1.connections.get_token(connection="github", identifier="u@x.com")
        tok = p2.connections.get_token(connection="github", identifier="u@x.com")

        self.assertEqual(tok.access_token, "token-in-P2")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_tenant_cache_not_shared_between_agent_clients_on_one_store(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"token": token_obj(accessToken="tenant-via-agent-1")}),
            make_response(CRED),
            make_response({"token": token_obj(accessToken="tenant-via-agent-2")}),
        ]
        store = MemoryTokenStore()
        one = self.make_client(
            ClientCredentialsProvider(client_id="cid1", client_secret="s"), store=store
        )
        two = self.make_client(
            ClientCredentialsProvider(client_id="cid2", client_secret="s"), store=store
        )

        one.connections.get_tenant_token(connection="github", tenant_id="t1")
        tok = two.connections.get_tenant_token(connection="github", tenant_id="t1")

        self.assertEqual(tok.access_token, "tenant-via-agent-2")

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

        tok = client.connections.wait_for_connection(
            connection="github",
            identifier="u@x.com",
            poll_interval=0.0,
            timeout=5.0,
        )

        self.assertEqual(tok.access_token, "gho_downstream_token")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_get_connect_url(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),  # phase 1
            make_response({"url": "https://api.descope.com/connect?app=github"}),  # connect
        ]
        client = self._agent_client()

        url = client.connections.get_connect_url(
            connection="github",
            identifier="u@x.com",
            scopes=["repo"],
            redirect_url="https://app/cb",
        )

        self.assertEqual(url, "https://api.descope.com/connect?app=github")
        args, kwargs = mock_request.call_args  # the connect call
        self.assertEqual(args[1], CONNECT)
        opts = kwargs["json"]["options"]
        self.assertEqual(opts["scopes"], ["repo"])
        self.assertEqual(opts["redirectUrl"], "https://app/cb")
        self.assertNotIn("userId", kwargs["json"])  # connect body carries no userId

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_not_connected_reports_why_there_is_no_connect_url(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"error": "not found"}, status=404),
            make_response({"errorDescription": "redirect URL not allowed"}, status=400),
        ]
        client = self._agent_client()

        with self.assertRaises(ConnectionAuthorizationRequired) as ctx:
            client.connections.get_token(connection="github", identifier="user@example.com")

        self.assertIsNone(ctx.exception.connect_url)
        self.assertIn("400", ctx.exception.connect_error)
        self.assertIn("redirect URL not allowed", ctx.exception.connect_error)
        self.assertIn("redirect URL not allowed", str(ctx.exception))

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_get_connect_url_raises_with_descope_reason(self, mock_request):
        mock_request.side_effect = [
            make_response(CRED),
            make_response({"errorDescription": "redirect URL not allowed"}, status=400),
        ]
        client = self._agent_client()

        with self.assertRaises(ConnectUrlFailed) as ctx:
            client.connections.get_connect_url(connection="github", identifier="u@x.com")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("redirect URL not allowed", str(ctx.exception))

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_get_connect_url_raises_when_response_has_no_url(self, mock_request):
        mock_request.side_effect = [make_response(CRED), make_response({})]
        client = self._agent_client()

        with self.assertRaises(ConnectUrlFailed):
            client.connections.get_connect_url(connection="github", identifier="u@x.com")

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


class _UserBoundProvider(AccessTokenProvider):
    """A user's token plus a confidential client, like a CibaProvider with a secret."""

    def __init__(self, user_jwt):
        super().__init__(access_token=user_jwt)

    def client_auth(self):
        return {"client_id": "cid", "client_secret": "s"}


class _IdentifiedUserProvider(_UserBoundProvider):
    """A user-bound provider with a stable identity (like CibaProvider), counting
    how often its credential is resolved."""

    def __init__(self, user_jwt, identity):
        super().__init__(user_jwt)
        self.identity = identity
        self.credential_calls = 0

    def identity_key(self):
        return self.identity

    async def get_credential(self):
        self.credential_calls += 1
        return await super().get_credential()


@patch("asyncio.sleep", AsyncMock())
class TestResourcesExchange(common.AgentAuthTest):
    """Resource tokens: client_credentials for the agent itself, token exchange for a user."""

    def _agent_client(self):
        return self.make_client(ClientCredentialsProvider(client_id="cid", client_secret="s"))

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_agent_itself_uses_client_credentials_with_resource(self, mock_request):
        # Descope applies client-access Policies only to a client_credentials
        # request that names the resource; a self token-exchange is refused.
        mock_request.return_value = make_response(
            {"access_token": "resource_at", "token_type": "Bearer", "expires_in": 3600, "scope": "read"}
        )
        client = self._agent_client()

        tok = client.resources.get_token(resource="urn:my-api", scopes=["read"])

        self.assertEqual(tok.access_token, "resource_at")
        self.assertEqual(tok.scopes, ["read"])
        self.assertEqual(mock_request.call_count, 1)  # no phase-1 token needed
        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], "/oauth2/v1/apps/token")
        self.assertEqual(kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(kwargs["data"]["resource"], "urn:my-api")
        self.assertEqual(kwargs["data"]["scope"], "read")
        self.assertEqual(kwargs["data"]["client_id"], "cid")
        self.assertEqual(kwargs["data"]["client_secret"], "s")
        self.assertNotIn("subject_token", kwargs["data"])

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_user_scoped_exchange_authenticates_the_agent_client(self, mock_request):
        mock_request.return_value = make_response({"access_token": "resource_at"})
        client = self._agent_client()

        client.resources.get_token(resource="urn:my-api", act_as_user_token="user_jwt")

        args, kwargs = mock_request.call_args
        self.assertEqual(args[1], "/oauth2/v1/apps/token")
        self.assertEqual(kwargs["data"]["subject_token"], "user_jwt")
        self.assertEqual(kwargs["data"]["client_id"], "cid")
        self.assertEqual(kwargs["data"]["client_secret"], "s")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_user_scoped_tokens_are_not_shared_across_users(self, mock_request):
        # One shared agent client serving two users must never hand user A's
        # Resource token to user B from the cache.
        mock_request.side_effect = [
            make_response({"access_token": "alice_resource_at", "expires_in": 3600}),
            make_response({"access_token": "bob_resource_at", "expires_in": 3600}),
        ]
        client = self._agent_client()

        alice = client.resources.get_token(resource="urn:my-api", act_as_user_token="alice_jwt")
        bob = client.resources.get_token(resource="urn:my-api", act_as_user_token="bob_jwt")
        alice_again = client.resources.get_token(
            resource="urn:my-api", act_as_user_token="alice_jwt"
        )

        self.assertEqual(alice.access_token, "alice_resource_at")
        self.assertEqual(bob.access_token, "bob_resource_at")
        self.assertEqual(alice_again.access_token, "alice_resource_at")  # cached per user
        self.assertEqual(mock_request.call_count, 2)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_user_scoped_token_is_not_served_to_the_agent_itself(self, mock_request):
        mock_request.side_effect = [
            make_response({"access_token": "alice_resource_at", "expires_in": 3600}),
            make_response({"access_token": "agent_resource_at", "expires_in": 3600}),
        ]
        client = self._agent_client()

        client.resources.get_token(resource="urn:my-api", act_as_user_token="alice_jwt")
        own = client.resources.get_token(resource="urn:my-api")

        self.assertEqual(own.access_token, "agent_resource_at")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_shared_store_does_not_mix_agent_clients_for_one_user(self, mock_request):
        # Two agentic clients on one shared store, acting for the same user, must
        # each get a token minted with themselves as act.sub.
        mock_request.side_effect = [
            make_response({"access_token": "a_resource_at", "expires_in": 3600}),
            make_response({"access_token": "b_resource_at", "expires_in": 3600}),
        ]
        store = MemoryTokenStore()
        a = self.make_client(ClientCredentialsProvider(client_id="a", client_secret="s"), store=store)
        b = self.make_client(ClientCredentialsProvider(client_id="b", client_secret="s"), store=store)

        tok_a = a.resources.get_token(resource="urn:my-api", act_as_user_token="alice_jwt")
        tok_b = b.resources.get_token(resource="urn:my-api", act_as_user_token="alice_jwt")

        self.assertEqual(tok_a.access_token, "a_resource_at")
        self.assertEqual(tok_b.access_token, "b_resource_at")
        self.assertEqual(mock_request.call_args.kwargs["data"]["client_id"], "b")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_shared_store_does_not_mix_agent_own_tokens(self, mock_request):
        # Without act_as_user_token each client asks for its own token; a shared
        # store must not serve one client's Resource token to another client.
        mock_request.side_effect = [
            make_response({"access_token": "a_resource_at", "expires_in": 3600}),
            make_response({"access_token": "b_resource_at", "expires_in": 3600}),
        ]
        store = MemoryTokenStore()
        a = self.make_client(ClientCredentialsProvider(client_id="a", client_secret="s"), store=store)
        b = self.make_client(ClientCredentialsProvider(client_id="b", client_secret="s"), store=store)

        tok_a = a.resources.get_token(resource="urn:my-api")
        tok_b = b.resources.get_token(resource="urn:my-api")
        tok_a_again = a.resources.get_token(resource="urn:my-api")

        self.assertEqual(tok_a.access_token, "a_resource_at")
        self.assertEqual(tok_b.access_token, "b_resource_at")
        self.assertEqual(tok_a_again.access_token, "a_resource_at")  # still cached
        self.assertEqual(mock_request.call_count, 2)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_user_bound_credential_is_exchanged_and_keyed_per_user(self, mock_request):
        # A confidential client whose phase-1 credential represents a user (as
        # with CIBA) exchanges that credential. Two such clients for different
        # users on one shared store must not share a Resource token.
        mock_request.side_effect = [
            make_response({"access_token": "alice_resource_at", "expires_in": 3600}),
            make_response({"access_token": "bob_resource_at", "expires_in": 3600}),
        ]
        store = MemoryTokenStore()
        alice = self.make_client(_UserBoundProvider("alice_jwt"), store=store)
        bob = self.make_client(_UserBoundProvider("bob_jwt"), store=store)

        tok_alice = alice.resources.get_token(resource="urn:my-api")
        tok_bob = bob.resources.get_token(resource="urn:my-api")

        self.assertEqual(tok_alice.access_token, "alice_resource_at")
        self.assertEqual(tok_bob.access_token, "bob_resource_at")
        data = mock_request.call_args.kwargs["data"]
        self.assertEqual(data["grant_type"], "urn:ietf:params:oauth:grant-type:token-exchange")
        self.assertEqual(data["subject_token"], "bob_jwt")
        self.assertEqual(data["client_id"], "cid")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_identified_provider_serves_cache_before_resolving_credential(self, mock_request):
        # A provider with a stable identity (CIBA) keys the cache by that identity,
        # so a cached Resource token never triggers a refresh or a new approval,
        # and the entry survives the phase-1 credential's rotation.
        mock_request.return_value = make_response(
            {"access_token": "alice_resource_at", "expires_in": 3600}
        )
        provider = _IdentifiedUserProvider("alice_jwt", "cred:ciba:P:cid:alice")
        client = self.make_client(provider)

        first = client.resources.get_token(resource="urn:my-api")
        # Rotate the phase-1 token: a digest-keyed entry would now miss.
        provider._access_token = "alice_jwt_rotated"
        provider._cached = None
        again = client.resources.get_token(resource="urn:my-api")

        self.assertEqual(first.access_token, "alice_resource_at")
        self.assertEqual(again.access_token, "alice_resource_at")
        self.assertEqual(mock_request.call_count, 1)
        self.assertEqual(provider.credential_calls, 1)  # only on the cache miss
        self.assertEqual(mock_request.call_args.kwargs["data"]["subject_token"], "alice_jwt")

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_identified_providers_are_keyed_per_identity(self, mock_request):
        mock_request.side_effect = [
            make_response({"access_token": "alice_resource_at", "expires_in": 3600}),
            make_response({"access_token": "bob_resource_at", "expires_in": 3600}),
        ]
        store = MemoryTokenStore()
        alice = self.make_client(_IdentifiedUserProvider("alice_jwt", "id:alice"), store=store)
        bob = self.make_client(_IdentifiedUserProvider("bob_jwt", "id:bob"), store=store)

        self.assertEqual(
            alice.resources.get_token(resource="urn:my-api").access_token, "alice_resource_at"
        )
        self.assertEqual(
            bob.resources.get_token(resource="urn:my-api").access_token, "bob_resource_at"
        )

    def test_ciba_identity_is_per_user(self):
        alice = CibaProvider(client_id="cid", client_secret="s", login_hint="alice@x.com")
        bob = CibaProvider(client_id="cid", client_secret="s", login_hint="bob@x.com")
        self.make_client(alice)
        self.make_client(bob)
        self.assertIsNotNone(alice.identity_key())
        self.assertNotEqual(alice.identity_key(), bob.identity_key())
        # Providers without one stable subject key by the credential instead.
        self.assertIsNone(
            ClientCredentialsProvider(client_id="cid", client_secret="s").identity_key()
        )
        self.assertIsNone(AccessTokenProvider(access_token="t").identity_key())

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_error_mapping_follows_the_oauth_error(self, mock_request):
        # Every Resource request carries the client secret, so go by the OAuth
        # error, not the HTTP status. Legacy envelope (strict OAuth errors off) too.
        cases = [
            (401, {"error": "invalid_client"}, CredentialAcquisitionFailed),
            (
                400,
                {"errorCode": "E074130", "errorDescription": "invalid_client",
                 "errorMessage": "Invalid client id"},
                CredentialAcquisitionFailed,
            ),
            (400, {"error": "unauthorized_client"}, PolicyDenied),
            (400, {"error": "invalid_target"}, PolicyDenied),
            (403, {"error": "access_denied"}, PolicyDenied),
            (
                400,
                {"error": "invalid_scope", "error_description": "Requested scope not granted"},
                PolicyDenied,
            ),
            (
                400,
                {"errorCode": "E063313", "errorDescription": "unauthorized_client",
                 "errorMessage": "Client is not authorized"},
                PolicyDenied,
            ),
            (400, {"errorCode": "E063309", "errorMessage": "Scope not allowed"}, PolicyDenied),
            (403, {"message": "forbidden"}, PolicyDenied),
            (400, {"error": "invalid_request"}, TokenExchangeFailed),
            (401, {"error": "invalid_token"}, TokenExchangeFailed),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status, body=body):
                mock_request.reset_mock()
                mock_request.return_value = make_response(body, status=status)
                client = self._agent_client()
                with self.assertRaises(AgentAuthError) as ctx:
                    client.resources.get_token(resource="urn:my-api")
                self.assertIs(type(ctx.exception), expected)

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_exchange_without_confidential_client_is_rejected(self, mock_request):
        # A bare user token has no client to authenticate the exchange, and
        # Descope rejects unauthenticated token-exchange requests.
        client = self.make_client(AccessTokenProvider(access_token="user_jwt"))
        with self.assertRaises(AgentAuthError) as ctx:
            client.resources.get_token(resource="urn:my-api")
        self.assertIn("ClientCredentialsProvider", str(ctx.exception))
        mock_request.assert_not_called()

    @patch("httpx.AsyncClient.request", new_callable=AsyncMock)
    def test_resource_token_sends_audience(self, mock_request):
        mock_request.return_value = make_response(
            {"access_token": "resource_at", "token_type": "Bearer"}
        )
        client = self._agent_client()

        client.resources.get_token(
            resource="urn:my-api", audience=["https://api.acme.com"], act_as_user_token="u"
        )

        _, kwargs = mock_request.call_args  # the token-exchange call
        self.assertEqual(kwargs["data"]["audience"], ["https://api.acme.com"])

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
        mock_request.return_value = make_response({"error": "access_denied"}, status=403)
        client = self._agent_client()
        with self.assertRaises(PolicyDenied):
            client.resources.get_token(resource="urn:my-api")
