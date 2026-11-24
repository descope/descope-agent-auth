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

    def test_masks_token_exchange_tokens(self):
        masked = _redact(
            {
                "subject_token": "user.jwt",
                "actor_token": "agent.jwt",
                "client_assertion": "signed.jwt",
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            }
        )
        self.assertEqual(masked["subject_token"], _REDACTED)
        self.assertEqual(masked["actor_token"], _REDACTED)
        self.assertEqual(masked["client_assertion"], _REDACTED)
        self.assertEqual(
            masked["subject_token_type"], "urn:ietf:params:oauth:token-type:access_token"
        )

    def test_masks_authorization_details(self):
        masked = _redact(
            {"authorization_details": '[{"type":"payment_initiation","amount":"15.00"}]'}
        )
        self.assertEqual(masked["authorization_details"], _REDACTED)

    def test_masks_nested(self):
        masked = _redact({"options": {"assertion": "x", "prompt": "consent"}})
        self.assertEqual(masked["options"]["assertion"], _REDACTED)
        self.assertEqual(masked["options"]["prompt"], "consent")
