"""Shared test scaffolding, in the Descope python-sdk style.

Tests are ``unittest.TestCase`` subclasses that patch the HTTP layer with
``unittest.mock`` and assert with ``self.assertEqual`` / ``self.assertRaises``.
The SDK core is async, so the Descope wire layer is mocked at
``httpx.AsyncClient.request`` (via ``unittest.mock.AsyncMock``) using
``make_response`` (a ``MagicMock`` shaped like the SDK's ``HttpResponse`` consumer
expectations). Tests drive the synchronous ``AgentAuthClient`` facade, so their
bodies stay synchronous; the facade runs the async core on a background loop.
"""

from __future__ import annotations

import time
import unittest
from typing import Optional
from unittest.mock import MagicMock

from descope_agent_auth import AgentAuthClient

DEFAULT_BASE_URL = "https://api.descope.com"
PROJECT_ID = "P2test"


def make_response(json_data=None, *, status: int = 200, text: Optional[str] = None):
    """Build a mock ``httpx.Response`` usable as a mocked HTTP call return value.

    Mirrors what ``descope_agent_auth._http.HttpClient`` reads off a response:
    ``status_code``, ``json()``, and ``text``.
    """
    m = MagicMock()
    m.status_code = status
    m.json.return_value = {} if json_data is None else json_data
    m.text = text if text is not None else str(json_data or "")
    return m


def token_obj(**overrides):
    """A representative Descope outbound token object (phase-2 response payload)."""
    obj = {
        "id": "tok_1",
        "appId": "github",
        "userId": "user@example.com",
        "accessToken": "gho_downstream_token",
        "accessTokenType": "Bearer",
        "accessTokenExpiry": str(int(time.time()) + 3600),
        "hasRefreshToken": False,
        "scopes": ["repo"],
    }
    obj.update(overrides)
    return obj


class AgentAuthTest(unittest.TestCase):
    """Base class providing a client factory bound to the dummy project."""

    def make_client(self, credential, **kwargs) -> AgentAuthClient:
        return AgentAuthClient(
            project_id=PROJECT_ID,
            base_url=DEFAULT_BASE_URL,
            credential=credential,
            **kwargs,
        )
