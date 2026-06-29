# @descope/agent-auth (TypeScript)

Client-side SDK for **homegrown / custom-built agents**. It does two things:

1. **Signs your agent in** to Descope.
2. **Gets the tokens** it needs — Connection or Resource tokens from the Descope vault.

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

## Sign-in providers

How the agent authenticates to Descope — pass one as `credential`.

| Provider                    | When                                                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------------------------ |
| `ClientCredentialsProvider` | autonomous agent, no user                                                                              |
| `DeviceCodeProvider`        | headless agent (no browser)                                                                            |
| `AuthorizationCodeProvider` | agent with a browser (PKCE)                                                                            |
| `CibaProvider`              | out-of-band user approval (also backs the approval gate)                                               |
| `AccessTokenProvider`       | bring your own Descope access token (e.g. a user's token from your app's login) for user-scoped access |
| `ManagementKeyProvider`     | privileged, **not recommended** (bypasses Policies; requires `allowManagementKey: true`)               |

For a user-scoped call on a shared client, pass `actAsUserToken: <user jwt>` to
`connections.getToken` / `resources.getToken`.

## Scopes

Omit `scopes` on the exchange and the Connection's configured defaults are used.
Pass `scopes` and they **fully override** the defaults (not clamped to a subset).
The guardrail on what an agent may obtain is Policies plus downstream
consent — not the default-scope list.

## Scripts

| Script                 | Purpose                                               |
| ---------------------- | ----------------------------------------------------- |
| `npm run build`        | dual CJS + ESM bundle with type declarations (rollup) |
| `npm test`             | Jest + nock with coverage                             |
| `npm run lint`         | ESLint (airbnb-typescript)                            |
| `npm run format-check` | Prettier check                                        |

## What's included

All credential providers, Connection and Resource token exchange, a pluggable
token store that persists and refreshes credentials across restarts, a CIBA
approval gate (`requireApproval`), the `withConnection` tool wrapper, and the
fetch/execute `mode` seam. See the
[quickstart](../docs/quickstart.md) and the
[framework cookbook](../docs/FRAMEWORKS.md).

`mode: 'execute'` is reserved for Descope's hosted execution endpoint and turns on
when that endpoint is available.

> A few endpoint paths (device authorization, CIBA backchannel, the resource
> token-exchange parameters) are centralized in `src/endpoints.ts` with comments
> noting they should be confirmed against your project's OIDC discovery document.
