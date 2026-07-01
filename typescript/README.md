# @descope/agent-auth (TypeScript)

Client-side SDK for custom-built agents. It signs your agent in to Descope and fetches
the Connection or Resource tokens its tools need from the vault. It's the OAuth
**client** side — not for building MCP servers (use the Descope MCP SDK for that). Runs
on Node, Cloudflare Workers, Deno, Bun, and browsers, and works with any framework via
the tool wrapper.

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
  credential: new ClientCredentialsProvider({
    clientId: 'agent-client-id',
    clientSecret: 'agent-client-secret',
  }),
});

try {
  const github = await client.connections.getToken({
    connection: 'github',
    identifier: 'user@example.com', // the user the agent acts for
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

Pass one as `credential`.

| Provider | When |
| --- | --- |
| `ClientCredentialsProvider` | autonomous agent, no user |
| `DeviceCodeProvider` | headless agent (no browser) |
| `CibaProvider` | out-of-band user approval (also backs the approval gate) |
| `JwtBearerProvider` | exchange a signed JWT from a trusted issuer (RFC 7523) |
| `AccessTokenProvider` | bring your own user access token (user-scoped access) |
| `ManagementKeyProvider` | privileged, **not recommended** (bypasses Policies; needs `allowManagementKey: true`) |

For a user-scoped call on a shared client, pass `actAsUserToken: <user jwt>` to
`connections.getToken` / `resources.getToken`.

## Scopes

Omit `scopes` → the Connection's configured defaults. Pass `scopes` → they **fully
override** the defaults (not clamped). The guardrail is Policies plus downstream
consent, not the scope list.

## What's included

All sign-in providers, Connection and Resource token exchange, a pluggable token store
(persists and refreshes across restarts), a CIBA approval gate (`requireApproval`), the
`withConnection` tool wrapper, and an MCP auth adapter
(`descopeMcpConnectionAuthProvider` / `descopeMcpResourceAuthProvider`). See the
[quickstart](../docs/quickstart.md) and [framework cookbook](../docs/FRAMEWORKS.md).

## Scripts

| Script | Purpose |
| --- | --- |
| `npm run build` | dual CJS + ESM bundle with type declarations |
| `npm test` | Jest + nock with coverage |
| `npm run lint` | ESLint (airbnb-typescript) |
| `npm run format-check` | Prettier check |

> A few endpoint paths (device authorization, CIBA backchannel, resource
> token-exchange parameters) live in `src/endpoints.ts`, with comments to confirm
> against your project's OIDC discovery document.
