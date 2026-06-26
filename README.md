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

## Two-phase mental model

| Phase | What | How |
| --- | --- | --- |
| **1 — Acquire** | get a Descope credential | `ClientCredentials` · `DeviceCode` · `AuthorizationCode` · `CIBA` · `ManagementKey` |
| **2 — Exchange** | trade it for a vault token | `connections.getToken(...)` · `resources.getToken(...)` |

Configure phase 1 once at init, then call phase 2 repeatedly. Refresh of the
phase-1 token and the downstream tokens happens transparently underneath.

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
