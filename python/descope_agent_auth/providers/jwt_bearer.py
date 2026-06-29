"""JwtBearerProvider -- exchange a signed external JWT for a Descope credential.

RFC 7523 (``urn:ietf:params:oauth:grant-type:jwt-bearer``): present a JWT issued by a
**trusted issuer you registered in Descope** (e.g. a cloud provider's workload-identity
OIDC token, or another IdP) and Descope validates it against that issuer's JWKs and
issues its own token. Use when the agent already holds a signed assertion of its
identity rather than a client secret or a Descope access token.

Requires the Descope client to have the **JWT Bearer** grant enabled and the issuer
registered as trusted (issuer URL + JWKs). The ``assertion`` may be a string or a
zero-arg callable returning a fresh JWT (useful for rotating workload tokens).
"""

from __future__ import annotations

from typing import Callable, List, Optional, Union

from .._endpoints import GRANT_JWT_BEARER, OAUTH2_TOKEN
from ..errors import CredentialAcquisitionFailed
from ..types import Credential, CredentialKind
from .base import CredentialProvider, _err, token_response_to_credential


class JwtBearerProvider(CredentialProvider):
    kind = CredentialKind.AGENT_TOKEN

    def __init__(
        self,
        *,
        client_id: str,
        assertion: Union[str, Callable[[], str]],
        scopes: Optional[List[str]] = None,
    ) -> None:
        super().__init__()
        self._client_id = client_id
        self._assertion = assertion
        self._scopes = scopes or []

    def _resolve_assertion(self) -> str:
        # A callable lets the caller hand over a *fresh* JWT each acquisition (the
        # external assertion is itself short-lived).
        return self._assertion() if callable(self._assertion) else self._assertion

    async def _acquire(self) -> Credential:
        data = {
            "grant_type": GRANT_JWT_BEARER,
            "client_id": self._client_id,
            "assertion": self._resolve_assertion(),
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        resp = await self.http.post_form(OAUTH2_TOKEN, data=data)
        if not resp.ok:
            raise CredentialAcquisitionFailed(
                f"jwt-bearer exchange failed ({resp.status_code}): "
                f"{_err(resp.json) or resp.text}"
            )
        return token_response_to_credential(resp.json, kind=self.kind)

    def _storage_key(self) -> str:
        return f"cred:jwt_bearer:{self._project_id}:{self._client_id}"

    def _refresh_client_auth(self) -> dict:
        return {"client_id": self._client_id}
