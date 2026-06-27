"""Acting for a user: fetch their Connection token (e.g. GitHub).

A user-level Connection token can only be fetched with the *user's* Descope access
token (or a management key) — so this example uses `AccessTokenProvider`. If the
user hasn't linked the account yet, the SDK raises `ConnectionAuthorizationRequired`
carrying the connect URL you'd send them to.

    set -a; source ../.env; set +a
    python user_connection.py
"""

from __future__ import annotations

from _config import base_url, optional, preview, require

from descope_agent_auth import AccessTokenProvider, AgentAuthClient
from descope_agent_auth.errors import ConnectionAuthorizationRequired


def main() -> None:
    connection = optional("CONNECTION_NAME", "github")
    identifier = require("DESCOPE_USER_IDENTIFIER")

    client = AgentAuthClient(
        project_id=require("DESCOPE_PROJECT_ID"),
        base_url=base_url(),
        credential=AccessTokenProvider(access_token=require("DESCOPE_USER_JWT")),
    )

    try:
        token = client.connections.get_token(connection=connection, identifier=identifier)
    except ConnectionAuthorizationRequired as exc:
        print(f"'{identifier}' hasn't connected '{connection}' yet.")
        print(f"Send them to the connect URL to consent:\n  {exc.connect_url}")
        print("Then re-run this script — the next fetch will succeed.")
        return

    print(f"Got a '{connection}' token for {identifier}:")
    print(f"  access_token = {preview(token.access_token)}")
    print(f"  scopes       = {token.scopes}")
    print(f"  expires_at   = {token.expires_at}")


if __name__ == "__main__":
    main()
