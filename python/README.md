# descope-agent-auth (Python)

Client-side SDK for custom-built agents. It signs your agent in to Descope and fetches
the Connection or Resource tokens its tools need from the vault. It's the OAuth
**client** side — not for building MCP servers (use the Descope MCP SDK for that), and
it works with any framework via the tool wrapper.

## Install

```bash
pip install descope-agent-auth
```

## Quickstart (autonomous agent)

```python
from descope_agent_auth import AgentAuthClient, ClientCredentialsProvider
from descope_agent_auth.errors import ConnectionAuthorizationRequired

client = AgentAuthClient(
    project_id="P2abc...",
    credential=ClientCredentialsProvider(
        client_id="agent-client-id",
        client_secret="agent-client-secret",
    ),
)

try:
    github = client.connections.get_token(
        connection="github",
        identifier="user@example.com",   # the user the agent acts for
        # scopes=["repo"],               # optional; overrides the Connection defaults
    )
    print(github.access_token)
except ConnectionAuthorizationRequired as e:
    # Send the user to e.connect_url to complete OAuth consent, then retry.
    print("connect first:", e.connect_url)
```

## Sign-in providers

Pass one as `credential=`.

| Provider | When |
| --- | --- |
| `ClientCredentialsProvider` | autonomous agent, no user |
| `DeviceCodeProvider` | headless agent (no browser) |
| `CibaProvider` | out-of-band user approval (also backs the approval gate) |
| `JwtBearerProvider` | exchange a signed JWT from a trusted issuer (RFC 7523) |
| `AccessTokenProvider` | bring your own user access token (user-scoped access) |
| `ManagementKeyProvider` | privileged, **not recommended** (bypasses Policies; needs `allow_management_key=True`) |

For a user-scoped call on a shared client, pass `act_as_user_token=<user jwt>` to
`connections.get_token` / `resources.get_token`.

## Scopes

Omit `scopes` → the Connection's configured defaults. Pass `scopes` → they **fully
override** the defaults (not clamped). The guardrail is Policies plus downstream
consent, not the scope list.

## What's included

All sign-in providers, Connection and Resource token exchange, a pluggable token store
(persists and refreshes across restarts), a CIBA approval gate (`require_approval`), the
`with_connection` tool wrapper, and an MCP auth adapter
(`descope_agent_auth.integrations.mcp`). See the
[quickstart](../docs/quickstart.md) and [framework cookbook](../docs/FRAMEWORKS.md).

> A few endpoint paths (device authorization, CIBA backchannel, resource
> token-exchange parameters) live in `_endpoints.py`, with comments to confirm against
> your project's OIDC discovery document.
