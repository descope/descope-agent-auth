"""The three-line tool ergonomic: @with_connection injects a fresh, scoped token.

You write a tool as `fn(token, identifier, ...)`; the wrapper fetches the Connection
token for that identity and passes it in. The `ConnectionAuthorizationRequired`
re-auth signal still propagates, so the caller can surface the connect URL.

    set -a; source ../.env; set +a
    python tool_ergonomic.py
"""

from __future__ import annotations

from _config import base_url, optional, preview, require

from descope_agent_auth import AccessTokenProvider, AgentAuthClient, with_connection
from descope_agent_auth.errors import ConnectionAuthorizationRequired


def main() -> None:
    connection = optional("CONNECTION_NAME", "github")
    identifier = require("DESCOPE_USER_IDENTIFIER")

    client = AgentAuthClient(
        project_id=require("DESCOPE_PROJECT_ID"),
        base_url=base_url(),
        credential=AccessTokenProvider(access_token=require("DESCOPE_USER_JWT")),
    )

    # The tool's body never touches exchange logic — it just receives `token`.
    @with_connection(client, connection=connection)
    def whoami(token: str, identifier: str) -> str:
        # A real tool would call the provider's API with `token` here.
        return f"would call '{connection}' as {identifier} with {preview(token)}"

    try:
        print(whoami(identifier=identifier))
    except ConnectionAuthorizationRequired as exc:
        print(f"Connect '{connection}' first: {exc.connect_url}")


if __name__ == "__main__":
    main()
