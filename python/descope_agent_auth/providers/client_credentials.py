"""ClientCredentialsProvider -- autonomous agent, no user in the loop.

The simplest phase-1 path: exchange ``client_id`` + ``client_secret`` for an
access token. A client secret is unavoidable here -- it is intrinsic to an agent
authenticating as itself.
"""

from __future__ import annotations

import base64
from typing import Dict, List, Optional

from .._endpoints import GRANT_CLIENT_CREDENTIALS, OAUTH2_APPS_TOKEN
from ..errors import CredentialAcquisitionFailed
from ..types import Credential, CredentialKind
from .base import CredentialProvider, _err, token_response_to_credential


class ClientCredentialsProvider(CredentialProvider):
    kind = CredentialKind.AGENT_TOKEN
    # Agentic Clients are inbound apps: acquire and refresh on the inbound-apps server.
    refresh_endpoint = OAUTH2_APPS_TOKEN
    # The agent client itself: its own Resource tokens use client_credentials.
    acts_as_client = True

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        scopes: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes or []

    def _basic_auth(self) -> str:
        raw = f"{self._client_id}:{self._client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    async def _acquire(self) -> Credential:
        data = {"grant_type": GRANT_CLIENT_CREDENTIALS}
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        # Agentic Clients are inbound apps, served by the /v1/apps/<projectId>
        # authorization server, whose token endpoint is /oauth2/v1/apps/token.
        resp = await self.http.post_form(
            OAUTH2_APPS_TOKEN, data=data, headers={"Authorization": self._basic_auth()}
        )
        if not resp.ok:
            raise CredentialAcquisitionFailed(
                f"client_credentials acquisition failed ({resp.status_code}): "
                f"{_err(resp.json) or resp.text}"
            )
        return token_response_to_credential(resp.json, kind=self.kind)

    def _storage_key(self) -> str:
        return f"cred:client_credentials:{self._project_id}:{self._client_id}"

    def _refresh_client_auth(self) -> dict:
        # client_credentials tokens are re-acquired, not refresh-token rotated;
        # base.get_credential falls back to _acquire when there is no refresh token.
        return {}

    def client_auth(self) -> Optional[Dict[str, str]]:
        return {"client_id": self._client_id, "client_secret": self._client_secret}
