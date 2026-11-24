"""Every request identifies the SDK, like Descope's python-sdk and node-sdk do.

Descope analytics groups traffic by ``x-descope-sdk-name`` + ``x-descope-sdk-version``,
so this SDK uses its own name rather than ``python`` (the core python-sdk).
"""

from __future__ import annotations

import asyncio
import platform
import re
import unittest
from pathlib import Path

import httpx

import descope_agent_auth
from descope_agent_auth._http import HttpClient


def _send_and_capture_headers() -> httpx.Headers:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return httpx.Response(200, json={})

    async def run() -> None:
        client = HttpClient("https://api.descope.com", _transport=httpx.MockTransport(handler))
        await client.post_form("/oauth2/v1/apps/token", data={"grant_type": "x"})
        await client.aclose()

    asyncio.run(run())
    return seen["headers"]


class TestSdkHeaders(unittest.TestCase):
    def test_requests_carry_descope_sdk_headers(self):
        headers = _send_and_capture_headers()

        self.assertEqual(headers["x-descope-sdk-name"], "agent-auth-python")
        self.assertEqual(headers["x-descope-sdk-version"], descope_agent_auth.__version__)
        self.assertEqual(headers["x-descope-sdk-python-version"], platform.python_version())
        self.assertEqual(
            headers["user-agent"], f"descope-agent-auth-python/{descope_agent_auth.__version__}"
        )

    def test_version_matches_pyproject(self):
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
        assert match is not None
        self.assertEqual(descope_agent_auth.__version__, match.group(1))
