# AGENTS.md — integrating descope-agent-auth

You are an AI agent integrating this SDK into someone's app. Read this file
top-to-bottom: it is a decision procedure followed by complete, copy-pasteable
recipes. Follow the decision procedure first, pick exactly one recipe, then apply
the rules. Do not mix recipes.

Packages: `descope-agent-auth` (Python, `pip install descope-agent-auth`) and
`@descope/agent-auth` (TypeScript, `npm install @descope/agent-auth`). The APIs are
mirror images — TypeScript names are the camelCase of the Python ones.

---

## Step 0 — Is this the right SDK?

| The user is building… | Use this SDK? |
| --- | --- |
| A **custom agent** (any framework) whose **tools call APIs** and need tokens | ✅ **Yes** — this is exactly it. |
| An **MCP server** they need to protect (validate tokens, DCR, `tools/list`) | ❌ No — use Descope's MCP server SDKs (`@descope/mcp-express` or `descope-mcp`). Inside that server's tool handlers, you *may* use this SDK to fetch downstream tokens. |
| An agent that is only an **MCP client** to third-party MCP servers | ❌ No — the MCP client stack owns that OAuth. This SDK has no place to plug in unless you implement the tools yourself. |

This SDK is the **OAuth client side**: it gets the tokens the **tools you implement**
need. If Step 0 is ✅, continue.

---

## Step 1 — Which token does the tool need?

Pick by **what the tool calls**:

- **A third-party service (GitHub, Slack, Google, …) or an internal API whose
  key/OAuth token is stored in Descope** → a **Connection token**. Method:
  `connections.get_token` (per user) or `connections.get_tenant_token` (org-shared).
- **Your own API that you protect with Descope as the OAuth authorization server** →
  a **Resource token**. Method: `resources.get_token`.

If a tool calls two services, it needs two `get_token` calls.

## Step 2 — How does the agent sign in to Descope?

This is the `credential=` you pass once when constructing the client. Pick the
**first** row that matches:

| Situation | Provider | Can it read a **user-level** Connection token? |
| --- | --- | --- |
| Your app already logged the user in with Descope; you hold their JWT | `AccessTokenProvider(access_token=user_jwt)` | ✅ yes (scoped to that user) |
| Autonomous agent, no user in the loop | `ClientCredentialsProvider(client_id, client_secret)` | ❌ **no** — only tenant-level Connections + Resource tokens |
| Backend with no user JWT that must read **any** user's already-connected token | `ManagementKeyProvider(management_key, allow_management_key=True)` | ✅ yes, **but bypasses Policies** — guard it |
| Headless / CLI tool, user can authenticate interactively | `DeviceCodeProvider(client_id)` | ✅ yes (it yields a user token) |
| Need a specific user's out-of-band approval | `CibaProvider(client_id, login_hint=...)` | ✅ yes (it yields a user token) |
| You hold a signed JWT from a Descope-registered trusted issuer (RFC 7523) | `JwtBearerProvider(client_id, assertion=...)` | depends on the subject of the JWT |

Steps 1 + 2 select a recipe below.

---

## Recipe A — Act for a logged-in user (most common)

Use when your app already authenticated the user with Descope and you hold their
access token (`user_jwt`). Covers user-level Connection tokens **and** user-scoped
Resource tokens.

**Python**

```python
from descope_agent_auth import AgentAuthClient, AccessTokenProvider
from descope_agent_auth import ConnectionAuthorizationRequired

client = AgentAuthClient(
    project_id="P2...",                       # your Descope project id
    credential=AccessTokenProvider(access_token=user_jwt),
)

try:
    # identifier = the user the agent acts for. Resolve it SERVER-SIDE (see Rules).
    github = client.connections.get_token(connection="github", identifier=user_id)
    call_github_api(github.access_token)      # a fresh, scoped GitHub token
except ConnectionAuthorizationRequired as e:
    # The user has not linked GitHub yet. Send them to e.connect_url to consent,
    # then retry this call.
    return redirect(e.connect_url)
```

**TypeScript**

```ts
import {
  AgentAuthClient,
  AccessTokenProvider,
  ConnectionAuthorizationRequired,
} from '@descope/agent-auth';

const client = new AgentAuthClient({
  projectId: 'P2...',
  credential: new AccessTokenProvider({ accessToken: userJwt }),
});

try {
  const github = await client.connections.getToken({ connection: 'github', identifier: userId });
  callGithubApi(github.accessToken);
} catch (e) {
  if (e instanceof ConnectionAuthorizationRequired) return redirect(e.connectUrl);
  throw e;
}
```

One shared client, many users? Don't bind the client to one user — pass the user's
token per call instead: `get_token(..., act_as_user_token=user_jwt)` /
`getToken({ ..., actAsUserToken: userJwt })`.

A user-scoped Resource token is the same idea:
`client.resources.get_token(resource="urn:my-api", scopes=["read"])` (the user is the
subject) or `resources.getToken({ resource: 'urn:my-api', actAsUserToken: userJwt })`.

---

## Recipe B — Autonomous agent (acts as itself, no user)

Use for a backend agent with no user. It can mint **Resource tokens** (scoped to the
agent's own M2M identity) and read **tenant-level** (org-shared) Connection tokens
for a tenant it belongs to. It **cannot** read a user's Connection token — see Rules.

**Python**

```python
from descope_agent_auth import AgentAuthClient, ClientCredentialsProvider

client = AgentAuthClient(
    project_id="P2...",
    credential=ClientCredentialsProvider(client_id="...", client_secret="..."),
)

# Resource token for the agent's own identity:
res = client.resources.get_token(resource="urn:my-api", scopes=["read"])
# Tenant-level Connection token (org-shared, no user):
slack = client.connections.get_tenant_token(connection="slack", tenant_id="acme")
```

**TypeScript**

```ts
import { AgentAuthClient, ClientCredentialsProvider } from '@descope/agent-auth';

const client = new AgentAuthClient({
  projectId: 'P2...',
  credential: new ClientCredentialsProvider({ clientId: '...', clientSecret: '...' }),
});

const res = await client.resources.getToken({ resource: 'urn:my-api', scopes: ['read'] });
const slack = await client.connections.getTenantToken({ connection: 'slack', tenantId: 'acme' });
```

---

## Recipe C — Backend service acting for many users (management key)

Use for a background/batch service that has **no user JWT** but must read specific
users' already-connected tokens. A management key reads **any** user's token by
`identifier`. It **bypasses Policies** — treat it as privileged and restrict who can
invoke this path. It can only *read* tokens; it cannot perform a user's first-time
OAuth consent (that is always interactive — see Rules).

**Python**

```python
from descope_agent_auth import AgentAuthClient, ManagementKeyProvider

client = AgentAuthClient(
    project_id="P2...",
    credential=ManagementKeyProvider(management_key="K...", allow_management_key=True),
)
for user_id in batch:
    gh = client.connections.get_token(connection="github", identifier=user_id)
    # gh.access_token ...
```

**TypeScript**

```ts
import { AgentAuthClient, ManagementKeyProvider } from '@descope/agent-auth';

const client = new AgentAuthClient({
  projectId: 'P2...',
  credential: new ManagementKeyProvider({ managementKey: 'K...', allowManagementKey: true }),
});
const gh = await client.connections.getToken({ connection: 'github', identifier: userId });
```

---

## Recipe D — Drop a token into any framework's tool (wrapper)

Every framework defines a tool as a function. `with_connection` / `withConnection`
wraps that function so a fresh, scoped token is injected as the first argument. Works
in LangChain, LangGraph, OpenAI, Vercel AI, Mastra, CrewAI, the Anthropic SDK, etc.
Build the `client` once (any recipe above), then:

**Python**

```python
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):       # token is injected, already scoped + fresh
    return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]

repos = list_repos(identifier=user_id)   # raises ConnectionAuthorizationRequired if not connected
```

**TypeScript**

```ts
import { withConnection } from '@descope/agent-auth';

const listRepos = withConnection(
  client,
  { connection: 'github', scopes: ['repo'] },
  async (token, identifier) =>
    (await new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser()).data.map((r) => r.name),
);

const repos = await listRepos(userId);
```

Per-framework snippets (LangChain, LangGraph, ADK, OpenAI, Vercel AI, Mastra,
LlamaIndex, Cloudflare, CrewAI, AG2, …): see [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md).

---

## Rules (invariants — do not violate)

1. **Client-credentials CANNOT read a user-level Connection token.** A
   `ClientCredentialsProvider` (M2M) sign-in can only fetch **tenant-level**
   Connection tokens (`get_tenant_token`) and mint **Resource** tokens. To read a
   *user's* Connection token (`get_token(identifier=user_id)`), sign in with that
   user's access token (`AccessTokenProvider` / `act_as_user_token`) **or** a
   management key. There is no "agent + user id reads any user" shortcut.
2. **Resolve `identifier` server-side** — from your session / authenticated request /
   agent context. **Never** take it from model output or tool-call input; a model
   choosing the identifier is an account-takeover bug.
3. **`scopes` is override-or-default.** Omit `scopes` → the Connection's configured
   default scopes are used. Pass `scopes` → they **fully replace** the defaults (not
   clamped to a subset).
4. **First-time third-party consent is always interactive.** When `get_token` raises
   `ConnectionAuthorizationRequired`, the user must open `connect_url` in a browser
   and approve. There is no token-only shortcut. **CIBA does not replace this** — CIBA
   gets you a Descope *user* token, which is not (for example) a GitHub token; the
   user still consents to the provider in a browser. A bare management key cannot do
   the initial consent either.
5. **Management key bypasses Policies.** It requires `allow_management_key=True` /
   `allowManagementKey: true` and is not the default path. Restrict who can call it.
6. **Never log token values.** `VaultToken.access_token` is a secret. The SDK already
   redacts tokens; don't undo that by printing `.access_token` or the raw response.
7. **`audience` is a list of strings**, not a single string:
   `resources.get_token(resource="urn:my-api", audience=["https://api.example.com"])`.

---

## Errors to handle

All extend `AgentAuthError` (match with `isinstance` / `instanceof`).

| Error | Means | What to do |
| --- | --- | --- |
| `ConnectionAuthorizationRequired` | user hasn't connected; carries `connect_url` / `connectUrl` | send the user to the URL, then retry the call (or use `wait_for_connection`) |
| `PolicyDenied` | the credential lacks Policy permission | surface a permission error; do not retry blindly |
| `ApprovalDenied` / `ApprovalTimeout` | a CIBA approval gate was rejected / timed out | tell the user the action wasn't approved |
| `CredentialAcquisitionFailed` | the agent couldn't sign in to Descope (bad creds, device/CIBA timeout) | check the `credential=` config |
| `TokenExchangeFailed` | other token-fetch failure | inspect the message; usually config/transport |

Catch `ConnectionAuthorizationRequired` specifically; let the rest propagate unless
you have a reason to handle them.

---

## After integrating — verify

Run the repo's checks if you changed SDK code:

```bash
# Python
cd python && pip install -e ".[dev]" && pytest -q && ruff check descope_agent_auth
# TypeScript
cd typescript && npm ci && npm test && npm run lint && npm run build
```

For integrating into a user's app (no SDK change), confirm: the client constructs
without error, a `get_token` call returns a `VaultToken`, and
`ConnectionAuthorizationRequired` is handled on the unconnected path.

---

## Deeper references

- [docs/quickstart.md](docs/quickstart.md) — full walkthrough, deployment patterns, token storage & refresh, the CIBA approval gate.
- [docs/api-reference.md](docs/api-reference.md) — every public symbol, exact signatures, types.
- [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) — per-framework tool snippets.
- [examples/](examples/) — runnable Python + TypeScript agents.
