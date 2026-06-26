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

```
                              ┌──────────────────── phase 2 ────────────────────┐
 Client ID + Secret ─▶ Descope OAuth token ─┬─▶ connections.get_token ─▶ Connection token (API key / OAuth)
 (or Management Key) ────────────────────────┘└─▶ resources.get_token  ─▶ Resource token (token-exchange)
```

- A **Connection token** is pulled from the vault. When the phase-1 credential is
  an agent OAuth token, **Connection Policies** govern what it may obtain; a
  Management Key is unrestricted.
- A **Resource token** is minted via the **token-exchange** grant. (This needs an
  OAuth agent identity — it does not apply to a Management Key.)

Configure phase 1 once; call phase 2 repeatedly. The phase-1 token and the
downstream tokens are cached and refreshed transparently — you ask for a token and
get a currently-valid one.

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
