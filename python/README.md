# descope-agent-auth (Python)

Client-side SDK for **homegrown / custom-built agents**. It does two things:

1. **Acquire** a Descope credential for the agent (phase 1).
2. **Exchange** that credential for Connection or Resource tokens from the Descope vault (phase 2).

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

## Phase-1 providers

| Provider | When |
| --- | --- |
| `ClientCredentialsProvider` | autonomous agent, no user |
| `DeviceCodeProvider` | headless agent (no browser) |
| `AuthorizationCodeProvider` | agent with a browser (PKCE) |
| `CibaProvider` | out-of-band user approval (also backs the phase-2 approval gate) |
| `AccessTokenProvider` | bring your own Descope access token (e.g. a user's token from your app's login) for user-scoped access |
| `ManagementKeyProvider` | privileged, **not recommended** (bypasses Connection Policies; requires `allow_management_key=True`) |

For a user-scoped call on a shared client, pass `act_as_user_token=<user jwt>` to
`connections.get_token` / `resources.get_token`.

## Scopes

Omit `scopes` on the exchange and the Connection's configured defaults are used.
Pass `scopes` and they **fully override** the defaults (not clamped to a subset).
The guardrail on what an agent may obtain is Connection Policies plus downstream
consent — not the default-scope list.

## Status

Implements phases 1–7 of the build spec: types/errors/HTTP, all credential
providers, the pluggable token store, the Connection/Resource exchange, the CIBA
approval **gate** (`require_approval`), the `with_connection` tool wrapper, and the
fetch/execute **execution seam** (`mode`). Only the hosted-execution endpoint
itself (`mode="execute"`) is stubbed, pending core eng. See
[docs/standalone-connections.md](../docs/standalone-connections.md) and the
[framework cookbook](../docs/FRAMEWORKS.md).

> Some endpoint paths (device authorization, CIBA backchannel, resource-token
> mapping) are centralized in `_endpoints.py` and flagged **UNVERIFIED** — confirm
> them against your project's OIDC discovery document before production use.
