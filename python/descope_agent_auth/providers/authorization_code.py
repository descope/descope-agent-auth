"""AuthorizationCodeProvider -- agents with a browser available.

Standard redirect-based auth-code flow with PKCE. The SDK builds the authorize
URL and exchanges the returned code for tokens; the caller owns the redirect
plumbing in their app. Because the redirect happens out-of-band, this provider is
constructed in two styles:

  * Build the authorize URL, send the user, capture the code, then call
    ``complete(code)`` -- which yields the first credential and seeds refresh.
  * Or construct it with an already-obtained ``authorization_code`` for one-shot
    server-side exchange.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import List, Optional
from urllib.parse import urlencode

from .._endpoints import GRANT_AUTHORIZATION_CODE, OAUTH2_AUTHORIZE, OAUTH2_TOKEN
from ..errors import CredentialAcquisitionFailed
from ..types import Credential, CredentialKind
from .base import CredentialProvider, _err, token_response_to_credential


def _gen_pkce() -> tuple:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


class AuthorizationCodeProvider(CredentialProvider):
    kind = CredentialKind.AGENT_TOKEN

    def __init__(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: Optional[List[str]] = None,
        client_secret: Optional[str] = None,
        authorization_code: Optional[str] = None,
        code_verifier: Optional[str] = None,
        base_url_for_authorize: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._scopes = scopes or ["openid"]
        self._client_secret = client_secret
        self._code: Optional[str] = authorization_code
        self._verifier = code_verifier
        self._base_for_authorize = base_url_for_authorize

    # -- redirect plumbing helpers (caller-driven) --------------------------

    def build_authorize_url(self, *, state: Optional[str] = None) -> str:
        """Build the authorize URL (with PKCE) for the caller to redirect to.

        Stores the generated ``code_verifier`` on the provider for the later
        exchange. The returned URL is absolute if ``base_url_for_authorize`` was
        provided, else a path relative to the client ``base_url``.
        """
        verifier, challenge = _gen_pkce()
        self._verifier = verifier
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if state:
            params["state"] = state
        base = (self._base_for_authorize or "").rstrip("/")
        return f"{base}{OAUTH2_AUTHORIZE}?{urlencode(params)}"

    def complete(self, authorization_code: str) -> Credential:
        """Supply the code captured at the redirect and acquire the credential."""
        self._code = authorization_code
        return self.refresh()  # forces _acquire with the now-set code

    # -- provider hooks -----------------------------------------------------

    def _acquire(self) -> Credential:
        if not self._code:
            raise CredentialAcquisitionFailed(
                "no authorization_code available; call build_authorize_url(), redirect "
                "the user, then complete(code)"
            )
        data = {
            "grant_type": GRANT_AUTHORIZATION_CODE,
            "code": self._code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
        }
        if self._verifier:
            data["code_verifier"] = self._verifier
        if self._client_secret:
            data["client_secret"] = self._client_secret
        resp = self.http.post_form(OAUTH2_TOKEN, data=data)
        if not resp.ok:
            raise CredentialAcquisitionFailed(
                f"authorization_code exchange failed ({resp.status_code}): "
                f"{_err(resp.json) or resp.text}"
            )
        # An auth code is single-use; clear it so a later refresh uses refresh_token.
        self._code = None
        return token_response_to_credential(resp.json, kind=self.kind)

    def _storage_key(self) -> str:
        return f"cred:authz:{self._project_id}:{self._client_id}"

    def _refresh_client_auth(self) -> dict:
        out = {"client_id": self._client_id}
        if self._client_secret:
            out["client_secret"] = self._client_secret
        return out
