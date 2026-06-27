"""DeviceCodeProvider -- headless agents (no browser).

Starts the device authorization flow, surfaces a verification URL + user code via
``PendingAuthorization``, then polls the token endpoint until the user completes
the flow on another device.

Endpoint paths for the device-authorization request are UNVERIFIED -- see
``_endpoints.DEVICE_AUTHORIZATION`` and confirm against the project discovery doc.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional, Tuple

from .._endpoints import DEVICE_AUTHORIZATION, GRANT_DEVICE_CODE, OAUTH2_TOKEN
from ..errors import CredentialAcquisitionFailed
from ..types import Credential, CredentialKind, PendingAuthorization
from .base import CredentialProvider, _err, token_response_to_credential


class DeviceCodeProvider(CredentialProvider):
    kind = CredentialKind.AGENT_TOKEN

    def __init__(
        self,
        *,
        client_id: str,
        scopes: Optional[List[str]] = None,
        on_pending: Optional[Callable[[PendingAuthorization], None]] = None,
        max_wait_seconds: float = 300.0,
    ) -> None:
        super().__init__()
        self._client_id = client_id
        self._scopes = scopes or []
        # Called once with the verification URL/code so the caller can display it.
        self._on_pending = on_pending
        self._max_wait_seconds = max_wait_seconds

    async def _start(self) -> Tuple[str, PendingAuthorization]:
        """Return ``(device_code, pending)``. The device_code is kept local and
        never placed into ``pending`` (which a caller may log)."""
        data = {"client_id": self._client_id}
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        resp = await self.http.post_form(DEVICE_AUTHORIZATION, data=data)
        if not resp.ok or not resp.json:
            raise CredentialAcquisitionFailed(
                f"device authorization request failed ({resp.status_code}): "
                f"{_err(resp.json) or resp.text}"
            )
        body = resp.json
        device_code = body.get("device_code")
        if not device_code:
            raise CredentialAcquisitionFailed("device authorization response missing device_code")
        expires_in = body.get("expires_in")
        pending = PendingAuthorization(
            verification_uri=body.get("verification_uri"),
            verification_uri_complete=body.get("verification_uri_complete"),
            user_code=body.get("user_code"),
            interval_seconds=float(body.get("interval", 5)),
            expires_at=time.time() + float(expires_in) if expires_in else None,
        )
        return device_code, pending

    async def _acquire(self) -> Credential:
        device_code, pending = await self._start()
        if self._on_pending:
            self._on_pending(pending)

        interval = pending.interval_seconds
        deadline = min(
            pending.expires_at or (time.time() + self._max_wait_seconds),
            time.time() + self._max_wait_seconds,
        )
        while time.time() < deadline:
            await asyncio.sleep(interval)
            resp = await self.http.post_form(
                OAUTH2_TOKEN,
                data={
                    "grant_type": GRANT_DEVICE_CODE,
                    "device_code": device_code,
                    "client_id": self._client_id,
                },
            )
            if resp.ok:
                return token_response_to_credential(resp.json, kind=self.kind)
            error = (resp.json or {}).get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise CredentialAcquisitionFailed(
                f"device flow failed: {_err(resp.json) or resp.text}"
            )
        raise CredentialAcquisitionFailed("device flow timed out before user approval")

    def _storage_key(self) -> str:
        return f"cred:device:{self._project_id}:{self._client_id}"

    def _refresh_client_auth(self) -> dict:
        # Device flow is a public client: refresh needs the client_id.
        return {"client_id": self._client_id}
