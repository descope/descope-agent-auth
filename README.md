# Descope Agent Auth SDK

A client-side SDK (Python and TypeScript) that makes it easy to wire a custom
agent to Descope. It does two things and only two things:

1. **Acquire** a Descope credential for the agent.
2. **Exchange** that credential for **Connection tokens** or **Resource tokens** from the Descope vault.

Everything else — tool code, API wrappers, a connector catalog — is out of scope
by design. This is the auth substrate an agent's tool calls sit on top of, not a
runtime tool catalog.

## Who this is for

- ✅ **Homegrown / custom-built agents** — agents you write yourself, in any
  framework (LangChain, LangGraph, Google ADK, OpenAI, Vercel AI, Mastra,
  LlamaIndex, Cloudflare Agents, AG2/AutoGen, CrewAI, TanStack AI, the Anthropic
  SDK, and more). It puts your agent on the **OAuth client** side: getting and
  using scoped tokens to act for a user or itself.
- ❌ **Not** for building MCP servers. Making an MCP server an OAuth 2.1 protected
  resource (DCR, metadata endpoints, token validation, `tools/list` filtering) is
  the *resource-server* side — that's the **Descope MCP SDK**. This SDK is the
  *requester* side. They compose (an agent can be both) but they don't merge.

**One core SDK, not one per framework.** Every framework defines a tool as a
function; the `with_connection` / `withConnection` wrapper drops a fresh, scoped
token into that function — so there's nothing to install per framework. It runs on
Node, Cloudflare Workers, Deno, Bun, and browsers. See the
**[framework cookbook](docs/FRAMEWORKS.md)** for a copy-paste snippet per framework.

## What kind of token does your agent need?

To call any service, your agent ultimately needs one of **two kinds of token**.
The SDK fetches both, through two entry points.

### 1. A Connection token — `client.connections.get_token(...)`

A **Connection** is a credential stored in the Descope **Connections vault**. It is
either:

- an **API key** — a stored secret for a service, held at either:
  - the **tenant level** (one key for your whole organization), or
  - the **user + tenant level** (a per-user key for a third-party API the agent
    calls on that user's behalf); or
- a **third-party OAuth token** — for an OAuth provider set up from Descope's
  **Connection template library** or a custom Connection (GitHub, Slack, Google,
  …), scoped to the agent's identity.

You pass the `identifier` (the user/principal the agent acts for) and optionally a
`tenant_id`; the vault returns the right stored token, refreshed as needed. If the
user hasn't connected the account yet, you get `ConnectionAuthorizationRequired`
carrying a connect URL.

### 2. A Resource token — `client.resources.get_token(...)`

A **Resource** is an API *you* build and protect with **Descope as the OAuth
authorization server**. The SDK obtains a Descope-issued OAuth token scoped to that
Resource using the **OAuth token-exchange grant**
(`urn:ietf:params:oauth:grant-type:token-exchange`) — exchanging the agent's Descope
token for a Resource-scoped one.

| Your agent needs to… | Method | Token you get | Source |
| --- | --- | --- | --- |
| call a 3rd-party API with a stored key | `connections.get_token` | API key | Connections vault (tenant, or user + tenant) |
| call a 3rd-party OAuth provider | `connections.get_token` | provider OAuth token | Connections vault (template or custom) |
| call your own Descope-protected API | `resources.get_token` | Descope OAuth token | token-exchange grant |

```mermaid
flowchart LR
    Agent["Your agent<br/>(any framework)"] --> SDK["descope-agent-auth<br/>AgentAuthClient"]

    SDK -->|"connections.get_token()"| Vault[("Connections<br/>vault")]
    SDK -->|"resources.get_token()<br/>token-exchange grant"| AS["Descope<br/>OAuth authorization server"]

    Vault --> Key["API key<br/>tenant · or · user + tenant"]
    Vault --> TP["3rd-party OAuth token<br/>template or custom connection"]
    AS --> Res["Resource token<br/>(Descope-issued OAuth)"]

    Key --> Svc["Third-party service<br/>GitHub · Slack · Google …"]
    TP --> Svc
    Res --> MyAPI["Your Descope-protected API"]
```

## How the SDK gets those tokens

It starts with **how your agent authenticates to Descope** (phase 1), configured
once at init — and you have two choices:

- **OAuth Client ID + Client Secret** (the common case) — your agent is a
  first-class identity in your **Agent Directory**. The SDK gets a Descope OAuth
  access token using whichever **grant** fits:
  - `ClientCredentialsProvider` — autonomous agent, no user
  - `DeviceCodeProvider` — headless agent (device code)
  - `AuthorizationCodeProvider` — browser present (authorization code + PKCE)
  - `CibaProvider` — out-of-band user approval (CIBA)
- **Management Key** (`ManagementKeyProvider`) — use this only if you *don't* want
  the agent represented as a unique Agent in your Agent Directory. It's a static,
  high-privilege credential that **bypasses Connection Policies**, so it is not the
  recommended path (requires explicit opt-in).

Then, at runtime (phase 2), the SDK **exchanges** that phase-1 credential for the
token the agent actually needs:

```mermaid
flowchart LR
    CID["OAuth Client ID + Secret<br/>(agent in your Agent Directory)"] --> Tok["Descope<br/>OAuth access token"]
    MK["Management Key<br/>(no Agent Directory identity)"] -. "not recommended" .-> Tok

    Tok -->|"phase 2"| Conn["connections.get_token()"]
    Tok -->|"phase 2"| ResM["resources.get_token()"]

    Conn --> CTok["Connection token<br/>API key / OAuth · governed by Connection Policies"]
    ResM --> RTok["Resource token<br/>via token-exchange grant"]
```

- A **Connection token** is pulled from the vault. When the phase-1 credential is
  an agent OAuth token, **Connection Policies** govern what it may obtain; a
  Management Key is unrestricted.
- A **Resource token** is minted via the **token-exchange** grant. (This needs an
  OAuth agent identity — it does not apply to a Management Key.)

Configure phase 1 once; call phase 2 repeatedly. The phase-1 token and the
downstream tokens are cached and refreshed transparently — you ask for a token and
get a currently-valid one.

## How a credential gets into Descope

Before the agent can fetch a **Connection** token, that credential has to exist in
the Connections vault. There are three ways it gets there — the first is runtime
(driven by the SDK), the other two are design/admin time:

```mermaid
flowchart TD
    User["End user"] -->|"completes OAuth consent<br/>via the connect URL the SDK returns"| Vault[("Connections vault")]
    Admin["Admin"] -->|"adds an API key by hand<br/>in the Descope Console"| Vault
    Backend["Your backend / IaC"] -->|"adds an API key via the<br/>Descope Management API"| Vault
    Vault -.->|"later: connections.get_token()"| Agent["Your agent"]
```

- **User connect (via the SDK).** When you call `connections.get_token` and the
  user hasn't connected yet, the SDK raises `ConnectionAuthorizationRequired` with
  a **connect URL**. Send the user there; they complete the provider's OAuth
  consent; Descope stores the resulting token in the vault. The next
  `get_token` call succeeds. (This is the OAuth path — GitHub, Slack, Google, ….)
- **Console.** An admin pastes an API key into a Connection in the Descope Console
  (typical for a static third-party API key, at the tenant or user level).
- **Management API.** Your backend or infrastructure-as-code writes the API key
  programmatically.

Resource tokens need no provisioning step — they're minted on demand from your
agent's identity via token-exchange.

## End-to-end at runtime

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Your agent (SDK)
    participant Descope
    participant User
    participant Service as Provider / your API

    Note over Agent,Descope: Phase 1 — acquire (once)
    Agent->>Descope: authenticate (client credentials / device / authcode / CIBA)
    Descope-->>Agent: Descope OAuth access token

    Note over Agent,Descope: Phase 2 — exchange (per call)
    Agent->>Descope: connections.get_token(connection, identifier)
    alt user has not connected this account yet
        Descope-->>Agent: ConnectionAuthorizationRequired (connect_url)
        Agent-->>User: surface connect_url
        User->>Descope: complete OAuth consent
        Descope->>Descope: store provider token in the vault
        Agent->>Descope: retry connections.get_token(...)
    end
    Descope-->>Agent: scoped Connection token (refreshed as needed)
    Agent->>Service: call the API with the token
    Service-->>Agent: result
```

For a sensitive step you can also require a fresh CIBA **approval** before the
exchange — see [docs/standalone-connections.md](docs/standalone-connections.md).

## Packages

| Package | Path | Install |
| --- | --- | --- |
| Python | [`python/`](python/) | `pip install descope-agent-auth` |
| TypeScript | [`typescript/`](typescript/) | `npm install @descope/agent-auth` |

The surfaces are kept identical across both languages so the docs and mental model
transfer. See each package's README for a copy-pasteable quickstart.

## Status

Implements phases 1–7 of the build spec across both languages: types/errors/HTTP
layer, all five credential providers, the pluggable token store, the
Connection/Resource exchange (with the `ConnectionAuthorizationRequired` re-auth
signal and the agent-token-vs-management-key policy distinction), the CIBA approval
**gate** on exchange, the `with_connection` / `withConnection` tool wrapper, and the
fetch/execute **execution seam**. Only the hosted-execution endpoint itself
(`mode="execute"`) is stubbed, pending core eng.

Quickstarts: [standalone Connections](docs/standalone-connections.md) (first-class)
and [MCP-fronted](docs/mcp-fronted.md).

## Development

This is a release-please monorepo using Conventional Commits.

```bash
# Python
cd python && pip install -e ".[dev]" && pytest -q && ruff check descope_agent_auth

# TypeScript
cd typescript && npm ci && npm test && npm run lint && npm run build
```

## License

[MIT](LICENSE)
