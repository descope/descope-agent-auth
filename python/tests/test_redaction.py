"""Log-redaction tests: sensitive request fields must be masked before logging."""

from __future__ import annotations

import unittest

from descope_agent_auth._http import _REDACTED, _redact


class TestRedaction(unittest.TestCase):
    def test_masks_sensitive_keys(self):
        masked = _redact(
            {"assertion": "signed.jwt", "client_secret": "s", "client_id": "cid", "scope": "read"}
        )
        self.assertEqual(masked["assertion"], _REDACTED)  # jwt-bearer credential
        self.assertEqual(masked["client_secret"], _REDACTED)
        self.assertEqual(masked["client_id"], "cid")  # not sensitive
        self.assertEqual(masked["scope"], "read")

    def test_masks_nested(self):
        masked = _redact({"options": {"assertion": "x", "prompt": "consent"}})
        self.assertEqual(masked["options"]["assertion"], _REDACTED)
        self.assertEqual(masked["options"]["prompt"], "consent")
