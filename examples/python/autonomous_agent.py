"""Autonomous agent (client credentials, no user in the loop).

Shows the two token kinds an M2M agent can obtain:
  1. a **Resource token** (token-exchange, scoped to the agent itself), and
  2. a **tenant-level Connection token** (org-shared, no user) — if the agent's
     identity is associated with that tenant.

It cannot fetch a *user's* Connection token; that needs the user's token (see
user_connection.py).

    set -a; source ../.env; set +a
    python autonomous_agent.py
"""

from __future__ import annotations

import os

from _config import base_url, optional, preview, require

from descope_agent_auth import AgentAuthClient, ClientCredentialsProvider
from descope_agent_auth.errors import ConnectionAuthorizationRequired


def main() -> None:
    client = AgentAuthClient(
        project_id=require("DESCOPE_PROJECT_ID"),
        base_url=base_url(),
        credential=ClientCredentialsProvider(
            client_id=require("DESCOPE_CLIENT_ID"),
            client_secret=require("DESCOPE_CLIENT_SECRET"),
        ),
    )

    # 1. Resource token — minted from the agent's own identity.
    resource = optional("RESOURCE", "urn:my-api")
    res = client.resources.get_token(resource=resource, scopes=["read"])
    print(f"Resource token for '{resource}':")
    print(f"  access_token = {preview(res.access_token)}  scopes={res.scopes}")

    # 2. Tenant-level Connection token — org-shared, keyed by tenant (no user).
    tenant_id = os.environ.get("TENANT_ID")
    if not tenant_id:
        print("\nSet TENANT_ID to also try a tenant-level Connection token.")
        return

    connection = optional("CONNECTION_NAME", "slack")
    try:
        tok = client.connections.get_tenant_token(connection=connection, tenant_id=tenant_id)
    except ConnectionAuthorizationRequired:
        print(f"\nNo tenant-level '{connection}' token provisioned for tenant '{tenant_id}'.")
        print("Provision one in the Descope Console / Management API first.")
        return

    print(f"\nTenant token for '{connection}' / tenant '{tenant_id}':")
    print(f"  access_token = {preview(tok.access_token)}  scopes={tok.scopes}")


if __name__ == "__main__":
    main()
