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
  the *resource-server* side. This SDK is the *requester* side. They compose (an
  agent can be both) but they don't merge.

> **Building an MCP server?** Use Descope's MCP server SDKs instead:
> [`@descope/mcp-express`](https://docs.descope.com/mcp/mcp-express-sdk) (Node/Express)
> or the [`descope-mcp` Python SDK](https://docs.descope.com/mcp/python-sdk) —
> overview at [docs.descope.com/mcp](https://docs.descope.com/mcp). If your agent
> *sits behind* such a server, you can still use this SDK inside your tool handlers
> to fetch downstream tokens — resolve the user from the validated request and call
> `connections.get_token` / `resources.get_token` as usual.

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

- an **API key** — a stored secret for a service. The service can be a
  **third-party API _or_ one of your own internal APIs** — handy when you'd rather
  not put an existing API behind Descope OAuth scopes just to let an agent call it.
  Held at either:
  - the **tenant level** (one key for your whole organization), or
  - the **user + tenant level** (a per-user key the agent uses on that user's
    behalf); or
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
| call a **third-party or internal** API with a stored key | `connections.get_token` | API key | Connections vault (tenant, or user + tenant) |
| call a third-party OAuth provider | `connections.get_token` | provider OAuth token | Connections vault (template or custom) |
| call your own API with **Descope-issued OAuth scopes** | `resources.get_token` | Resource token (Descope OAuth) | token-exchange grant |

> Two ways to reach **your own** APIs: use a **Resource token** when you want
> Descope to mint OAuth tokens with scopes for it, or a Connection **API key** when
> you'd rather keep an existing internal API as-is.

The flow reads left to right — **ask → receive → call**. (The agent in ① and ② is
the same agent: it asks, gets the token back, then makes the call in ③.)

```mermaid
flowchart LR
    A1(["Your agent"]) -->|"① get_token()"| SDK["descope-agent-auth"]

    SDK -->|"connections"| Vault[("Connections vault")]
    SDK -->|"resources<br/>(token-exchange)"| AS["Descope OAuth AS"]

    Vault -->|"API key /<br/>3rd-party OAuth"| A2(["② agent now<br/>holds the token"])
    AS -->|"Resource token"| A2

    A2 -->|"③ call with the token"| TP["Third-party service<br/>GitHub · Slack · Google …"]
    A2 -->|"③ call with the token"| Own["Your own / internal APIs<br/>Resource OAuth · or · Connection API key"]
```

Either kind of token — a Connection token from the vault or a Resource token from
token-exchange — is returned to the agent (in the default `fetch` mode) and the
agent makes the call itself. Note that a Connection **API key** can target a
**third-party service _or_ one of your own internal APIs** — so you don't have to
put an existing API behind Descope OAuth just to let an agent call it.

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
- **A user's access token you already hold** (`AccessTokenProvider`) — if your app
  already logged the user in with Descope, hand that token to the agent directly
  (no re-authentication) for **user-scoped** access.
- **Management Key** (`ManagementKeyProvider`) — use this only if you *don't* want
  the agent represented as a unique Agent in your Agent Directory. It's a static,
  high-privilege credential that **bypasses Policies**, so it is not the
  recommended path (requires explicit opt-in).

Then, at runtime (phase 2), the SDK **exchanges** that phase-1 credential for the
token the agent actually needs:

```mermaid
flowchart LR
    CID["OAuth Client ID + Secret<br/>(agent in your Agent Directory)"] --> Tok["Descope<br/>OAuth access token"]
    MK["Management Key<br/>(no Agent Directory identity)"] -. "not recommended" .-> Tok

    Tok -->|"phase 2"| Conn["connections.get_token()"]
    Tok -->|"phase 2"| ResM["resources.get_token()"]

    Conn --> CTok["Connection token<br/>API key / OAuth · governed by Policies"]
    ResM --> RTok["Resource token<br/>via token-exchange grant"]
```

- A **Connection token** is pulled from the vault. When the phase-1 credential is
  an agent OAuth token, **Policies** govern what it may obtain; a
  Management Key is unrestricted.
- A **Resource token** is minted via the **token-exchange** grant. (This needs an
  OAuth agent identity — it does not apply to a Management Key.)

Configure phase 1 once; call phase 2 repeatedly. The phase-1 credential and the
downstream tokens are cached and refreshed transparently — you ask for a token and
get a currently-valid one. Both are persisted to the pluggable token store
(including refresh tokens), so a restarted or multi-process agent **refreshes
instead of re-authenticating** — important for device-code / authorization-code /
CIBA flows. See
[token storage & refresh](docs/standalone-connections.md#token-storage--refresh).

## Autonomous vs. acting for a user

**Autonomous agent (no user).** The agent authenticates as itself and acts on its
own behalf:

```python
client = AgentAuthClient(
    project_id="P2...",
    credential=ClientCredentialsProvider(client_id="...", client_secret="..."),
)
token = client.connections.get_token(connection="github", identifier="agent@acme.com")
```

**On behalf of a user (autonomous client + `identifier`).** One backend client
serves many users; its agent credential has the policy to read a named user's vault
token. Pass the **user id** per call — no user token needed:

```python
token = client.connections.get_token(connection="github", identifier=user_id)
```

**User-scoped (the agent wields the user's own Descope token).** When the agent
must act strictly as the user — and especially to mint a **user-scoped Resource
token** (the user's token becomes the token-exchange `subject_token`) — supply that
user's access token (the one you got from authorization code / device code / CIBA).
Two ways:

```python
# A) You already hold the user's token (e.g. from your app's login):
from descope_agent_auth import AccessTokenProvider

client = AgentAuthClient(project_id="P2...", credential=AccessTokenProvider(access_token=user_jwt))
gh  = client.connections.get_token(connection="github", identifier=user_id)   # user-scoped
res = client.resources.get_token(resource="urn:my-api", scopes=["read"])      # user-scoped (subject = user_jwt)

# B) One shared client, many users — pass the user token per call:
gh  = client.connections.get_token(connection="github", identifier=user_id, act_as_user_token=user_jwt)
res = client.resources.get_token(resource="urn:my-api", act_as_user_token=user_jwt)
```

```ts
// TypeScript — same two options
import { AccessTokenProvider } from '@descope/agent-auth';

const client = new AgentAuthClient({ projectId: 'P2...', credential: new AccessTokenProvider({ accessToken: userJwt }) });
await client.connections.getToken({ connection: 'github', identifier: userId });

// or per call on a shared client:
await client.connections.getToken({ connection: 'github', identifier: userId, actAsUserToken: userJwt });
await client.resources.getToken({ resource: 'urn:my-api', actAsUserToken: userJwt });
```

> Where does `user_jwt` come from? Your app authenticates the user with Descope
> (authorization code, device code, or CIBA) and gets their access token; you hand
> that token to the SDK. The `DeviceCodeProvider` / `AuthorizationCodeProvider` /
> `CibaProvider` can also acquire it for you — their resulting credential is the
> user's token and flows into phase 2 the same way.

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

## What's included

Both languages, identical surfaces:

- All credential providers: client credentials, device code, authorization code
  (PKCE), CIBA, management key, and bring-your-own access token.
- Connection and Resource token exchange, with the
  `ConnectionAuthorizationRequired` re-auth signal and the agent-token-vs-management-key
  distinction.
- A pluggable token store that persists and refreshes credentials (including
  refresh tokens) across restarts.
- A human-in-the-loop CIBA **approval gate** on sensitive calls.
- The `with_connection` / `withConnection` tool wrapper, plus a LangGraph
  `interrupt()` helper.

`mode: "execute"` (routing calls through Descope so the token never enters the
agent process) is reserved — the client accepts it today and turns it on when
Descope's hosted execution endpoint becomes available.

Quickstart: [standalone Connections](docs/standalone-connections.md), and the
[framework cookbook](docs/FRAMEWORKS.md).

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
