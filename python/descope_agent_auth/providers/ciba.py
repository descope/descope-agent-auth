"""CibaProvider -- out-of-band user approval (Client-Initiated Backchannel Auth).

CIBA does double duty (see spec):

  * As a phase-1 path, it acquires a user-bound token without the user being
    interactively present: the agent initiates, Descope pushes an approval to the
    user's registered device, and this provider polls until approval.
  * As a phase-2 gate, the same machinery requires a fresh approval before a single
    sensitive exchange/action. ``authenticate()`` is exposed for that reuse (the
    gate wiring itself lands in the exchange layer).

Endpoint paths and the CIBA grant-type string are UNVERIFIED -- see
``_endpoints.CIBA_AUTHENTICATE`` / ``GRANT_CIBA`` and confirm via discovery.
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional

from .._endpoints import CIBA_AUTHENTICATE, GRANT_CIBA, OAUTH2_TOKEN
from ..errors import ApprovalDenied, ApprovalTimeout, CredentialAcquisitionFailed
from ..types import Credential, CredentialKind
from .base import CredentialProvider, _err, token_response_to_credential


class CibaProvider(CredentialProvider):
    kind = CredentialKind.AGENT_TOKEN

    def __init__(
        self,
        *,
        client_id: str,
        login_hint: str,
        client_secret: Optional[str] = None,
        binding_message: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        max_wait_seconds: float = 120.0,
    ) -> None:
        super().__init__()
        self._client_id = client_id
        self._client_secret = client_secret
        self._login_hint = login_hint
        self._binding_message = binding_message
        self._scopes = scopes or ["openid"]
        self._max_wait_seconds = max_wait_seconds

    async def _acquire(self) -> Credential:
        return await self.authenticate(
            login_hint=self._login_hint,
            binding_message=self._binding_message,
            scopes=self._scopes,
            timeout_seconds=self._max_wait_seconds,
        )

    async def authenticate(
        self,
        *,
        login_hint: str,
        binding_message: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        timeout_seconds: float = 120.0,
    ) -> Credential:
        """Run one full CIBA cycle (initiate + poll) and return the user-bound token.

        Reused as both the acquisition flow and the phase-2 approval gate. Raises
        ``ApprovalDenied`` / ``ApprovalTimeout`` on rejection or expiry.
        """
        auth_req_id, interval, deadline = await self._initiate(login_hint, binding_message, scopes)
        deadline = min(deadline, time.time() + timeout_seconds)

        while time.time() < deadline:
            await asyncio.sleep(interval)
            resp = await self.http.post_form(OAUTH2_TOKEN, data=self._poll_body(auth_req_id))
            if resp.ok:
                return token_response_to_credential(resp.json, kind=self.kind)
            error = (resp.json or {}).get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error in ("access_denied", "denied"):
                raise ApprovalDenied("user rejected the CIBA approval request")
            if error == "expired_token":
                raise ApprovalTimeout("CIBA request expired before approval")
            raise CredentialAcquisitionFailed(
                f"CIBA flow failed: {_err(resp.json) or resp.text}"
            )
        raise ApprovalTimeout("CIBA request timed out before user approval")

    async def _initiate(
        self,
        login_hint: str,
        binding_message: Optional[str],
        scopes: Optional[List[str]],
    ) -> tuple:
        data = {
            "client_id": self._client_id,
            "login_hint": login_hint,
            "scope": " ".join(scopes or self._scopes),
        }
        if self._client_secret:
            data["client_secret"] = self._client_secret
        if binding_message:
            data["binding_message"] = binding_message
        resp = await self.http.post_form(CIBA_AUTHENTICATE, data=data)
        if not resp.ok or not resp.json:
            raise CredentialAcquisitionFailed(
                f"CIBA initiation failed ({resp.status_code}): {_err(resp.json) or resp.text}"
            )
        body = resp.json
        auth_req_id = body.get("auth_req_id")
        if not auth_req_id:
            raise CredentialAcquisitionFailed("CIBA initiation response missing auth_req_id")
        interval = float(body.get("interval", 5))
        expires_in = float(body.get("expires_in", self._max_wait_seconds))
        return auth_req_id, interval, time.time() + expires_in

    def _poll_body(self, auth_req_id: str) -> dict:
        body = {"grant_type": GRANT_CIBA, "auth_req_id": auth_req_id, "client_id": self._client_id}
        if self._client_secret:
            body["client_secret"] = self._client_secret
        return body

    def _storage_key(self) -> str:
        # Keyed by the user (login_hint): the acquired token is user-bound.
        return f"cred:ciba:{self._project_id}:{self._client_id}:{self._login_hint}"

    def _refresh_client_auth(self) -> dict:
        out = {"client_id": self._client_id}
        if self._client_secret:
            out["client_secret"] = self._client_secret
        return out
