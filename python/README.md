# descope-agent-auth (Python)

Client-side SDK for **homegrown / custom-built agents**. It does two things:

1. **Signs your agent in** to Descope.
2. **Gets the tokens** it needs — Connection or Resource tokens from the Descope vault.

Everything else (tool code, API wrappers, a connector catalog) is out of scope by design.

It puts your agent on the **OAuth client** side. It is **not** for building MCP
servers (the resource-server side — use the Descope MCP SDK for that). Works with
any agent framework via the tool wrapper — see the
[framework cookbook](../docs/FRAMEWORKS.md).

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
    base_url="https://api.descope.com",
    credential=ClientCredentialsProvider(
        client_id="agent-client-id",
        client_secret="agent-client-secret",
    ),
)

try:
    github = client.connections.get_token(
        connection="github",
        identifier="user@example.com",   # the principal the agent acts for
        # scopes=["repo"],               # optional; overrides the Connection defaults
    )
    print(github.access_token)
except ConnectionAuthorizationRequired as e:
    # Send the user to e.connect_url to complete OAuth consent, then retry.
    print("connect first:", e.connect_url)
```

## Sign-in providers

How the agent authenticates to Descope — pass one as `credential=`.

| Provider | When |
| --- | --- |
| `ClientCredentialsProvider` | autonomous agent, no user |
| `DeviceCodeProvider` | headless agent (no browser) |
| `AuthorizationCodeProvider` | agent with a browser (PKCE) |
| `CibaProvider` | out-of-band user approval (also backs the approval gate) |
| `AccessTokenProvider` | bring your own Descope access token (e.g. a user's token from your app's login) for user-scoped access |
| `ManagementKeyProvider` | privileged, **not recommended** (bypasses Policies; requires `allow_management_key=True`) |

For a user-scoped call on a shared client, pass `act_as_user_token=<user jwt>` to
`connections.get_token` / `resources.get_token`.

## Scopes

Omit `scopes` on the exchange and the Connection's configured defaults are used.
Pass `scopes` and they **fully override** the defaults (not clamped to a subset).
The guardrail on what an agent may obtain is Policies plus downstream
consent — not the default-scope list.

## What's included

All credential providers, Connection and Resource token exchange, a pluggable
token store that persists and refreshes credentials across restarts, a CIBA
approval gate (`require_approval`), the `with_connection` tool wrapper, and the
fetch/execute `mode` seam. See the
[quickstart](../docs/quickstart.md) and the
[framework cookbook](../docs/FRAMEWORKS.md).

`mode="execute"` is reserved for Descope's hosted execution endpoint and turns on
when that endpoint is available.

> A few endpoint paths (device authorization, CIBA backchannel, the resource
> token-exchange parameters) are centralized in `_endpoints.py` with comments
> noting they should be confirmed against your project's OIDC discovery document.
