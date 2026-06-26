# Standalone Connections quickstart

This is the **first-class** path: using `descope-agent-auth` on its own, with no
MCP server in front of it. Your agent acquires a Descope credential and exchanges
it for downstream provider tokens (GitHub, Slack, Google, ...) from the Descope
vault.

> If your agent sits behind an MCP server, use this SDK inside your tool handlers
> the same way. (To *build* the MCP server, use Descope's
> [MCP server SDKs](https://docs.descope.com/mcp) — this SDK is the client side.)

## The two phases

1. **Acquire** a Descope credential (configured once at init).
2. **Exchange** it for a Connection token (called repeatedly at runtime).

Refresh of both the Descope credential and the downstream tokens happens
transparently underneath — you ask for a token and get a currently-valid one.

## Prerequisites

- A Descope project, and an **Outbound App / Connection** configured for the
  provider you want (e.g. `github`), set up at design time in the Descope Console
  or via the Descope MCP server. Default scopes live on the Connection.
- A way for the agent to authenticate to Descope (see provider table below).

---

## Python

```bash
pip install descope-agent-auth
```

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
    # github.access_token is a downstream GitHub token, refreshed as needed.
    use_github(github.access_token)
except ConnectionAuthorizationRequired as e:
    # The user hasn't connected GitHub yet. Send them to e.connect_url to consent,
    # then retry the exchange.
    redirect_user_to(e.connect_url)
```

### Three-line tool ergonomic

```python
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):
    gh = GitHub(auth=token)            # token injected, already scoped + fresh
    return [r.name for r in gh.repos.list_for_authenticated_user()]

repos = list_repos(identifier="user@example.com")
# ConnectionAuthorizationRequired propagates if the user must connect first.
```

---

## TypeScript

```bash
npm install @descope/agent-auth
```

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
    identifier: 'user@example.com',
    // scopes: ['repo'],   // optional; overrides the Connection defaults
  });
  useGithub(github.accessToken);
} catch (e) {
  if (e instanceof ConnectionAuthorizationRequired) {
    redirectUserTo(e.connectUrl);
  } else {
    throw e;
  }
}
```

### Three-line tool ergonomic

```ts
import { withConnection } from '@descope/agent-auth';

const listRepos = withConnection(
  client,
  { connection: 'github', scopes: ['repo'] },
  async (token, identifier) => {
    const octokit = new Octokit({ auth: token });
    const { data } = await octokit.rest.repos.listForAuthenticatedUser();
    return data.map((r) => r.name);
  },
);

const repos = await listRepos('user@example.com');
```

---

## Picking a phase-1 provider

| Provider | Use when |
| --- | --- |
| `ClientCredentialsProvider` | autonomous agent, no user in the loop |
| `DeviceCodeProvider` | headless agent (no browser); shows a verification URL + code |
| `AuthorizationCodeProvider` | agent with a browser available (PKCE) |
| `CibaProvider` | the agent needs a specific user's approval out of band |
| `AccessTokenProvider` | you already hold a user's Descope access token (user-scoped access) |
| `ManagementKeyProvider` | privileged, **not recommended** — bypasses Policies |

### User-scoped access

To act as a specific user — and to mint **user-scoped Resource tokens** — present
that user's Descope access token (from your authorization-code / device-code / CIBA
login). Either configure the client with `AccessTokenProvider`, or pass
`act_as_user_token` / `actAsUserToken` per call on a shared client:

```python
from descope_agent_auth import AccessTokenProvider

# Option A — a client bound to the user's token:
client = AgentAuthClient(project_id="P2...", credential=AccessTokenProvider(access_token=user_jwt))
gh = client.connections.get_token(connection="github", identifier=user_id)

# Option B — one shared client, user token per call:
gh = client.connections.get_token(connection="github", identifier=user_id, act_as_user_token=user_jwt)
res = client.resources.get_token(resource="urn:my-api", act_as_user_token=user_jwt)
```

```ts
import { AccessTokenProvider } from '@descope/agent-auth';

const client = new AgentAuthClient({ projectId: 'P2...', credential: new AccessTokenProvider({ accessToken: userJwt }) });
await client.connections.getToken({ connection: 'github', identifier: userId });

// or per call on a shared client:
await client.connections.getToken({ connection: 'github', identifier: userId, actAsUserToken: userJwt });
```

## Scopes

- **Omit** `scopes` → the Connection's configured default scopes are used.
- **Pass** `scopes` → they fully override the defaults (not clamped to a subset).

The real guardrail on what an agent can obtain is **Policies** plus
downstream provider consent — not the default-scope list. The SDK never infers
scopes from agent intent; a request either omits them or pins an explicit set.

### Scopes and the connect URL

You define a tool's scopes in one place — `with_connection(scopes=[...])` /
`get_token(scopes=[...])` — and the SDK uses that same set for **both** the token
fetch **and** the connect URL it returns when the user hasn't connected yet. So the
consent screen requests exactly what that tool needs; a different tool with
different scopes produces a connect URL for those scopes. Omit `scopes` and the
connect URL uses the Connection's **default scopes** configured in Descope.

```python
@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier): ...
# If the user must connect first, e.connect_url already requests ["repo"].
```

Because the connect URL requests only the calling tool's scopes, a user may be
prompted to connect more than once as different tools need new scopes (incremental
consent). To get a single up-front consent, set the Connection's **default scopes**
to the superset (and call tools without `scopes`), or request the superset.

The connect endpoint nests these under `options` (`scopes`, `redirectUrl`, plus
`prompt`, `loginHint`, `resources`, `externalIdentifier`). The SDK places the call's
`scopes` and `redirect_url` there for you; pass any of the other fields via
`connect_options` (Python) / `connectOptions` (TS):

```python
client.connections.get_token(
    connection="github",
    identifier=user_id,
    scopes=["repo"],
    redirect_url="https://app/cb",
    connect_options={"prompt": ["consent"], "loginHint": "user@example.com"},
)
```

## Human-in-the-loop approval (CIBA gate)

For a sensitive exchange, require a fresh user sign-off on a trusted device before
the token is handed back. Configure an `approval` provider on the client, then pass
`require_approval` / `requireApproval` to the exchange.

```python
from descope_agent_auth import AgentAuthClient, CibaProvider, ApprovalRequest

client = AgentAuthClient(
    project_id="P2abc...",
    credential=ClientCredentialsProvider(client_id="...", client_secret="..."),
    approval=CibaProvider(client_id="...", login_hint="user@example.com"),
)

token = client.connections.get_token(
    connection="github",
    identifier="user@example.com",
    require_approval=ApprovalRequest(
        login_hint="user@example.com",
        binding_message="Approve the agent deleting branch protection",
    ),
)
# Blocks until the user approves on their device, else raises ApprovalDenied / ApprovalTimeout.
```

```ts
const client = new AgentAuthClient({
  projectId: 'P2abc...',
  credential: new ClientCredentialsProvider({ clientId: '...', clientSecret: '...' }),
  approval: new CibaProvider({ clientId: '...', loginHint: 'user@example.com' }),
});

const token = await client.connections.getToken({
  connection: 'github',
  identifier: 'user@example.com',
  requireApproval: {
    loginHint: 'user@example.com',
    bindingMessage: 'Approve the agent deleting branch protection',
  },
});
```

## Errors worth catching

| Error | Meaning |
| --- | --- |
| `ConnectionAuthorizationRequired` | user hasn't connected the account; carries `connect_url` / `connectUrl` |
| `PolicyDenied` | agent token lacks Policy permission |
| `ApprovalDenied` / `ApprovalTimeout` | the CIBA gate was rejected or timed out |
| `CredentialAcquisitionFailed` | phase 1 failed (bad client creds, device-flow timeout, ...) |
| `TokenExchangeFailed` | other phase-2 transport/validation failure |

## Token storage & refresh

The `store` holds **both** phases: the phase-1 Descope credential (including its
**refresh token**, kept beyond the access token's expiry) and the phase-2
downstream tokens. Everything is refreshed lazily on access — you ask for a token
and get a currently-valid one.

This matters most for **device code / authorization code / CIBA**: their tokens are
persisted with the refresh token, so a restarted or multi-process agent **refreshes
instead of re-running the interactive flow** (no second device prompt, browser
redirect, or CIBA push). `ClientCredentials` is simply re-acquired (no user
interaction); `ManagementKey` and bring-your-own `AccessTokenProvider` tokens are
not persisted.

By default everything is cached in-process (`MemoryTokenStore`) — fine for a single
long-running process, but lost on restart. For multi-process, serverless, or
restart-safe deployments, implement the `TokenStore` interface
(`get`/`set`/`delete`/`list`) over Redis, a database, or a secrets manager and pass
it as `store`.

> **Security:** with a persistent store, the credentials there now include
> **refresh tokens**. Treat the store as a secret store (encryption at rest, access
> controls). The SDK never logs token values.
