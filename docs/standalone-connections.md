# Standalone Connections quickstart

Use `descope-agent-auth` on its own: your agent acquires a Descope credential and
exchanges it for downstream provider tokens (GitHub, Slack, Google, ...) from the
Descope vault.

> Building an MCP server? Use this SDK inside your tool handlers to fetch downstream
> tokens. (To *protect* the MCP server itself, use Descope's
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
from descope_agent_auth import AgentAuthClient, AccessTokenProvider
from descope_agent_auth.errors import ConnectionAuthorizationRequired

# A *user-level* Connection token is fetched with that user's Descope access token
# (or a management key). A client-credentials / M2M agent token cannot read user
# tokens -- it can only fetch tenant-level Connection tokens or mint M2M-scoped
# Resource tokens. See "Picking a phase-1 provider" below.
client = AgentAuthClient(
    project_id="P2abc...",
    base_url="https://api.descope.com",
    credential=AccessTokenProvider(access_token=user_jwt),   # the user's Descope token
)

try:
    github = client.connections.get_token(
        connection="github",
        identifier="user@example.com",   # the user whose token you're fetching
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
  AccessTokenProvider,
  ConnectionAuthorizationRequired,
} from '@descope/agent-auth';

// A *user-level* Connection token is fetched with that user's Descope access token
// (or a management key). A client-credentials / M2M agent token cannot read user
// tokens -- it can only fetch tenant-level Connection tokens or mint M2M-scoped
// Resource tokens. See "Picking a phase-1 provider" below.
const client = new AgentAuthClient({
  projectId: 'P2abc...',
  baseUrl: 'https://api.descope.com',
  credential: new AccessTokenProvider({ accessToken: userJwt }), // the user's Descope token
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

> **What a credential can fetch differs.** Phase-1 auth and phase-2 fetch authority
> are not the same thing. A **user-level Connection token** (the common case —
> `connections.get_token(identifier=user_id)`) can only be fetched with **that
> user's access token** (`AccessTokenProvider` / `act_as_user_token`) or a
> **management key**. A client-credentials / M2M token **cannot** read user-level
> tokens; it can fetch **tenant-level** Connection tokens (when the client is
> associated with that tenant — not yet exposed on the SDK surface) and mint
> **Resource** tokens, which are scoped to the M2M client itself, not a user.

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

The connect endpoint nests these under `options`. The two documented fields are
`redirectUrl` and `scopes`, and the SDK fills both in for you (from `redirect_url`
and the call's `scopes`). `connect_options` (Python) / `connectOptions` (TS) is an
escape hatch for any **additional provider-specific OAuth passthrough** fields your
Connection supports — it is not a documented, user-binding mechanism:

```python
client.connections.get_token(
    connection="github",
    identifier=user_id,
    scopes=["repo"],
    redirect_url="https://app/cb",
    connect_options={"prompt": ["consent"]},   # provider passthrough; verify support
)
```

> **`connect_options` does not pick the user.** Descope binds the connection to
> whoever the connect request's **bearer token** identifies (the user's session /
> refresh JWT) — there is no documented body field to target an arbitrary user. This
> is why a backend with only a management key can't mint a user-bound connect URL out
> of thin air; see [How a user connects when the agent is a backend process](#how-a-user-connects-when-the-agent-is-a-backend-process).

## Token levels: user, user + tenant, and tenant

A Connection's tokens live at one of three levels. Which one you fetch — and who is
allowed to fetch it — differ:

| Level | Fetch with | Who can fetch |
| --- | --- | --- |
| **User** | `get_token(identifier=user_id)` | the user's access token, or a management key |
| **User + tenant** | `get_token(identifier=user_id, tenant_id=…)` | the user's access token, or a management key |
| **Tenant** (org-shared, no user) | `get_tenant_token(tenant_id=…)` | an M2M client associated with the tenant, or a management key |

**User vs. user + tenant.** One Connection can hold *several* tokens for the same
user — one per tenant — and they are **not interchangeable**. Omit `tenant_id` to get
the user's tenant-less token; pass it to get the tenant-bound one. Asking for a
tenant-bound token *without* its `tenant_id` reads as "not connected" and raises
`ConnectionAuthorizationRequired`. (The SDK keys its token cache on the tenant too,
so the two never collide.)

**Tenant-level** is the one Connection fetch an **autonomous agent** (client
credentials, no user token) can perform — the token belongs to the tenant, not a
user. It's admin/IaC-provisioned, so there's no connect-URL fallback on a miss.

```python
# User-level (the common case) — needs the user's token or a management key:
gh = client.connections.get_token(connection="github", identifier=user_id)

# Same user, a specific tenant's token for the same Connection:
gh_acme = client.connections.get_token(connection="github", identifier=user_id, tenant_id="acme")

# Tenant-level (org-shared, no user) — an M2M agent associated with the tenant can fetch it:
slack = client.connections.get_tenant_token(connection="slack", tenant_id="acme")
```

```ts
await client.connections.getToken({ connection: 'github', identifier: userId });
await client.connections.getToken({ connection: 'github', identifier: userId, tenantId: 'acme' });
await client.connections.getTenantToken({ connection: 'slack', tenantId: 'acme' });
```

## How a user connects when the agent is a backend process

The front-end path is simple: the user is present in a browser with a live Descope
session, your app calls `get_token`, catches `ConnectionAuthorizationRequired`, and
redirects them to `connect_url`. They consent, the token lands in the vault under
their identity, the retry succeeds.

A **backend job has neither a browser nor (usually) the user's live session token**,
so that path doesn't translate directly. The thing to understand first:

> Descope associates a connect URL with the user identified by the **bearer token on
> the connect request** — the user's session / refresh JWT. The request body is just
> `appId` + `options{ redirectUrl, scopes }`; there is **no documented field to name
> an arbitrary user**. So you cannot mint a *user-bound* connect URL from a bare
> management key plus an identifier — the identifier alone never reaches the consent
> screen.

That rules out "management key + user id → connect URL" as a server-side shortcut.
A backend-initiated connection therefore has to get a **user credential into the
loop** by one of these routes:

1. **Defer to the user's next interactive moment (simplest).** The backend doesn't
   build the URL at all. When `get_token` raises `ConnectionAuthorizationRequired`,
   record that this identity needs to connect (a flag, a queued task) and surface it
   the next time the user is in your front-end — where their live session token
   builds the connect URL the normal way. The agent retries once the vault has the
   token.

2. **Act as the user with a token you already hold.** If you've previously logged
   the user in (authorization-code / device-code / CIBA) and **persisted their
   refresh token** (the `store` keeps it), present that token via `act_as_user_token`
   so the connect URL is minted server-side under their identity. Deliver the URL
   **out of band** — email, Slack, in-app — and learn it finished by **polling**
   (retry `get_token`) or a **Descope webhook**.

   ```python
   try:
       client.connections.get_token(
           connection="github",
           identifier=user_id,
           act_as_user_token=stored_user_jwt,   # mints the connect URL as this user
       )
   except ConnectionAuthorizationRequired as e:
       email_user(user_id, e.connect_url)       # out-of-band delivery
       # later: poll get_token(...) again, or react to a Descope webhook, then fetch.
   ```

3. **Ask the user out of band via CIBA.** With no token on hand, use a `CibaProvider`
   to get a user-scoped Descope token through an out-of-band push to the user's
   device, then use it as `act_as_user_token` as in (2). CIBA is also the right tool
   when you want a fresh per-exchange approval — see the CIBA gate section below.

Whichever route, completion is asynchronous: **poll** by retrying `get_token` (it
succeeds once the vault holds the token) or subscribe to a **Descope webhook**.

### How other platforms model this

The contrast is worth stating plainly, because some platforms *do* key the connect
URL by your stable user id server-side with no session token:

| Platform | Backend-initiated connect |
| --- | --- |
| **Arcade** | `tools.authorize(tool, user_id=…)` returns an auth URL + id keyed by **your user id**; poll `auth.wait_for_completion(id)`. No user session needed. |
| **Scalekit** | "Connected accounts": create a connection link for a **user id**, hosted consent, email / magic-link delivery, **webhook** on completion. |
| **Auth0 (Token Vault)** | Interactive flows surface the authorize URL as an **interrupt**; async/backend uses **CIBA** to ask a specific user out of band. |
| **Descope** | The connect URL is bound by the **user token on the request**, not a body id — so a backend supplies that token (stored refresh token via `act_as_user_token`, or CIBA), or defers URL creation to the user's interactive moment. |

The practical upshot: with Descope you reach the same out-of-band outcome, but the
user identity comes from **a token you act as**, not an identifier in the connect
body.

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
