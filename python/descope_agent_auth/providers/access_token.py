"""AccessTokenProvider -- bring your own Descope access token.

Use when you *already hold* a Descope access token -- most commonly a **user's**
token obtained from your app's own login (its session, device-code, or CIBA) -- and
want the agent to act with it for **user-scoped** downstream access. No acquisition
happens: the SDK wields the token you supply (and refreshes only if you also provide
a refresh token).

    client = AgentAuthClient(
        project_id="P2...",
        credential=AccessTokenProvider(access_token=user_jwt),
    )
    # user-scoped: vault fetch + token-exchange both run as this user
    gh = client.connections.get_token(connection="github", identifier=user_id)

For a single shared (autonomous) client serving many users, prefer the per-call
``act_as_user_token=`` override on ``connections.get_token`` / ``resources.get_token``
instead of constructing a client per user.
"""

from __future__ import annotations

from typing import Optional

from ..types import Credential, CredentialKind
from .base import CredentialProvider


class AccessTokenProvider(CredentialProvider):
    kind = CredentialKind.AGENT_TOKEN

    def __init__(
        self,
        *,
        access_token: str,
        expires_at: Optional[float] = None,
        refresh_token: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._access_token = access_token
        self._expires_at = expires_at
        self._refresh_token = refresh_token

    def _acquire(self) -> Credential:
        # The token is supplied, not acquired; just hand it back.
        return Credential(
            token=self._access_token,
            kind=self.kind,
            expires_at=self._expires_at,
            refresh_token=self._refresh_token,
        )
