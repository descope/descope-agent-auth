# @descope/agent-auth (TypeScript)

Client-side SDK for **homegrown / custom-built agents**. It does two things:

1. **Acquire** a Descope credential for the agent (phase 1).
2. **Exchange** that credential for Connection or Resource tokens from the Descope vault (phase 2).

Everything else (tool code, API wrappers, a connector catalog) is out of scope by design.

It puts your agent on the **OAuth client** side. It is **not** for building MCP
servers (the resource-server side — use the Descope MCP SDK for that). Runs on Node,
Cloudflare Workers, Deno, Bun, and browsers, and works with any agent framework via
the tool wrapper — see the [framework cookbook](../docs/FRAMEWORKS.md).

## Install

```bash
npm install @descope/agent-auth
```

## Quickstart (autonomous agent)

```ts
import {
  AgentAuthClient,
  ClientCredentialsProvider,
  ConnectionAuthorizationRequired,
} from '@descope/agent-auth';

const client = new AgentAuthClient({
  projectId: 'P2abc...',
  baseUrl: 'https://api.descope.com',
  credential: new ClientCredentialsProvider({
    clientId: 'agent-client-id',
    clientSecret: 'agent-client-secret',
  }),
});

try {
  const github = await client.connections.getToken({
    connection: 'github',
    identifier: 'user@example.com', // the principal the agent acts for
    // scopes: ['repo'],            // optional; overrides the Connection defaults
  });
  console.log(github.accessToken);
} catch (e) {
  if (e instanceof ConnectionAuthorizationRequired) {
    // Send the user to e.connectUrl to complete OAuth consent, then retry.
    console.log('connect first:', e.connectUrl);
  } else {
    throw e;
  }
}
```

## Phase-1 providers

| Provider                    | When                                                                                                |
| --------------------------- | --------------------------------------------------------------------------------------------------- |
| `ClientCredentialsProvider` | autonomous agent, no user                                                                           |
| `DeviceCodeProvider`        | headless agent (no browser)                                                                         |
| `AuthorizationCodeProvider` | agent with a browser (PKCE)                                                                         |
| `CibaProvider`              | out-of-band user approval (also backs the phase-2 approval gate)                                    |
| `ManagementKeyProvider`     | privileged, **not recommended** (bypasses Connection Policies; requires `allowManagementKey: true`) |

## Scopes

Omit `scopes` on the exchange and the Connection's configured defaults are used.
Pass `scopes` and they **fully override** the defaults (not clamped to a subset).
The guardrail on what an agent may obtain is Connection Policies plus downstream
consent — not the default-scope list.

## Scripts

| Script                 | Purpose                                               |
| ---------------------- | ----------------------------------------------------- |
| `npm run build`        | dual CJS + ESM bundle with type declarations (rollup) |
| `npm test`             | Jest + nock with coverage                             |
| `npm run lint`         | ESLint (airbnb-typescript)                            |
| `npm run format-check` | Prettier check                                        |

## Status

Implements phases 1–7 of the build spec: types/errors/HTTP, all five credential
providers, the pluggable token store, the Connection/Resource exchange, the CIBA
approval **gate** (`requireApproval`), the `withConnection` tool wrapper, and the
fetch/execute **execution seam** (`mode`). Only the hosted-execution endpoint
itself (`mode: 'execute'`) is stubbed, pending core eng. See
[docs/standalone-connections.md](../docs/standalone-connections.md) and
[docs/mcp-fronted.md](../docs/mcp-fronted.md).

> Some endpoint paths (device authorization, CIBA backchannel, resource-token
> mapping) are centralized in `src/endpoints.ts` and flagged **UNVERIFIED** —
> confirm them against your project's OIDC discovery document before production use.
