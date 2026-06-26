"""Tests for the optional LangGraph integration (interrupt() conversion)."""

from __future__ import annotations

from unittest.mock import patch

from descope_agent_auth import ManagementKeyProvider
from descope_agent_auth.errors import ApprovalDenied, ConnectionAuthorizationRequired
from descope_agent_auth.integrations.langgraph import connection_tool, interrupt_payload

from . import common
from .common import make_response, token_obj


class _Pause(Exception):
    """Stand-in for langgraph's GraphInterrupt (interrupt() raises to pause)."""


def _mgmt():
    return ManagementKeyProvider(management_key="K", allow_management_key=True)


class TestLangGraphIntegration(common.AgentAuthTest):
    @patch("httpx.Client.request")
    def test_no_error_calls_fn_without_interrupting(self, mock_request):
        mock_request.return_value = make_response({"token": token_obj()})
        events = []

        @connection_tool(
            self.make_client(_mgmt()),
            connection="github",
            scopes=["repo"],
            interrupt=lambda payload: events.append(payload),
        )
        def list_repos(token, identifier):
            return f"{identifier}:{token}"

        self.assertEqual(list_repos(identifier="u@e.com"), "u@e.com:gho_downstream_token")
        self.assertEqual(events, [])  # interrupt never fired on the happy path

    @patch("httpx.Client.request")
    def test_pauses_on_connection_required(self, mock_request):
        mock_request.side_effect = [
            make_response({"error": "no"}, status=404),
            make_response({"url": "https://api.descope.com/connect?x=1"}),
        ]
        captured = {}

        def fake_interrupt(payload):
            captured.update(payload)
            raise _Pause()  # mimic GraphInterrupt pausing the graph

        @connection_tool(
            self.make_client(_mgmt()),
            connection="github",
            scopes=["repo"],
            interrupt=fake_interrupt,
        )
        def list_repos(token, identifier):  # pragma: no cover - not reached
            return token

        with self.assertRaises(_Pause):
            list_repos(identifier="u@e.com")
        self.assertEqual(captured["type"], "connection_authorization_required")
        self.assertEqual(captured["connect_url"], "https://api.descope.com/connect?x=1")

    @patch("httpx.Client.request")
    def test_retries_after_resume(self, mock_request):
        # 404 -> connect URL fetched -> interrupt returns (inline resume) -> retry succeeds.
        mock_request.side_effect = [
            make_response({"error": "no"}, status=404),
            make_response({"url": "https://api.descope.com/connect"}),
            make_response({"token": token_obj()}),
        ]
        calls = {"n": 0}

        def fake_interrupt(_payload):
            calls["n"] += 1
            return "resumed"

        @connection_tool(
            self.make_client(_mgmt()),
            connection="github",
            scopes=["repo"],
            interrupt=fake_interrupt,
        )
        def list_repos(token, identifier):
            return token

        self.assertEqual(list_repos(identifier="u@e.com"), "gho_downstream_token")
        self.assertEqual(calls["n"], 1)

    @patch("httpx.Client.request")
    def test_non_interrupt_errors_propagate(self, mock_request):
        mock_request.return_value = make_response({"error": "policy denied"}, status=403)

        @connection_tool(
            self.make_client(_mgmt()),
            connection="github",
            scopes=["repo"],
            interrupt=lambda _p: None,
        )
        def list_repos(token, identifier):  # pragma: no cover - not reached
            return token

        from descope_agent_auth.errors import PolicyDenied

        with self.assertRaises(PolicyDenied):
            list_repos(identifier="u@e.com")

    @patch("httpx.Client.request")
    def test_missing_langgraph_raises_friendly_importerror(self, mock_request):
        mock_request.side_effect = [
            make_response({"error": "no"}, status=404),
            make_response({"url": "https://api.descope.com/connect"}),
        ]

        @connection_tool(self.make_client(_mgmt()), connection="github")  # no interrupt passed
        def list_repos(token, identifier):  # pragma: no cover - not reached
            return token

        # langgraph is not installed in the test env, so the lazy default resolves
        # to a friendly ImportError when the interrupt actually needs to fire.
        with self.assertRaises(ImportError):
            list_repos(identifier="u@e.com")

    def test_interrupt_payload_shapes(self):
        car = ConnectionAuthorizationRequired(
            "x", connect_url="u", connection="github", identifier="i"
        )
        payload = interrupt_payload(car)
        self.assertEqual(payload["type"], "connection_authorization_required")
        self.assertEqual(payload["connect_url"], "u")
        self.assertEqual(interrupt_payload(ApprovalDenied("nope"))["type"], "approval_denied")
