# MCP-fronted quickstart

Use this path when your agent sits **behind an MCP server**. The two SDKs solve
different halves and compose cleanly:

| SDK | Side | Responsibility |
| --- | --- | --- |
| Descope **MCP SDK** | resource server | makes the MCP server an OAuth 2.1 protected resource: DCR, metadata endpoints, token validation, `tools/list` filtering |
| **descope-agent-auth** (this SDK) | requester | the agent acquires and wields credentials to act on a user's or its own behalf |

They don't merge. A single agent often uses both: the MCP SDK to *be* a protected
server, this SDK to *act as a client* against other services from inside its tools.

> If you have no MCP server, the standalone path is first-class — see
> [standalone-connections.md](standalone-connections.md).

## The shape

```
   user / caller
        │  (1) MCP request with an access token
        ▼
 ┌─────────────────────┐
 │  Your MCP server     │   ← Descope MCP SDK validates the token, filters tools
 │  (protected resource)│
 │                      │
 │   tool handler ──────┼──▶ descope-agent-auth
 │                      │      (2) exchange the validated identity for a
 │                      │          Connection token, then call the provider
 └─────────────────────┘
```

The MCP server has already authenticated the caller and holds a validated Descope
identity for the request. Inside a tool handler, this SDK exchanges that identity
for the downstream Connection token.

## Wiring the identity through

Two common arrangements:

1. **Agent-token passthrough.** The MCP server's validated access token *is* the
   Descope credential. Construct the client so phase 1 surfaces that token, then
   exchange per request with the caller's `identifier`.

2. **Autonomous server identity.** The MCP server authenticates to Descope as
   itself (client credentials) and exchanges on behalf of the named `identifier`
   it resolved from the validated request. Connection Policies govern what that
   server identity may pull.

The exchange call is identical either way — only the phase-1 provider differs.

### Python — inside an MCP tool handler

```python
from descope_agent_auth import AgentAuthClient, ClientCredentialsProvider
from descope_agent_auth.errors import ConnectionAuthorizationRequired

# Built once at server startup.
agent_auth = AgentAuthClient(
    project_id="P2abc...",
    credential=ClientCredentialsProvider(
        client_id="mcp-server-client-id",
        client_secret="mcp-server-client-secret",
    ),
)

async def handle_list_repos(request, mcp_context):
    # The MCP SDK has already validated the caller and resolved their identity.
    identifier = mcp_context.user_id            # server-side, never from tool input

    try:
        github = agent_auth.connections.get_token(
            connection="github",
            identifier=identifier,
            scopes=["repo"],
        )
    except ConnectionAuthorizationRequired as e:
        # Return the connect URL to the caller so they can authorize the connection.
        return {"needs_authorization": True, "connect_url": e.connect_url}

    gh = GitHub(auth=github.access_token)
    return {"repos": [r.name for r in gh.repos.list_for_authenticated_user()]}
```

### TypeScript — inside an MCP tool handler

```ts
import {
  AgentAuthClient,
  ClientCredentialsProvider,
  ConnectionAuthorizationRequired,
} from '@descope/agent-auth';

const agentAuth = new AgentAuthClient({
  projectId: 'P2abc...',
  credential: new ClientCredentialsProvider({
    clientId: 'mcp-server-client-id',
    clientSecret: 'mcp-server-client-secret',
  }),
});

export async function handleListRepos(request, mcpContext) {
  const identifier = mcpContext.userId; // resolved server-side from the validated request

  let github;
  try {
    github = await agentAuth.connections.getToken({
      connection: 'github',
      identifier,
      scopes: ['repo'],
    });
  } catch (e) {
    if (e instanceof ConnectionAuthorizationRequired) {
      return { needsAuthorization: true, connectUrl: e.connectUrl };
    }
    throw e;
  }

  const octokit = new Octokit({ auth: github.accessToken });
  const { data } = await octokit.rest.repos.listForAuthenticatedUser();
  return { repos: data.map((r) => r.name) };
}
```

## Surfacing re-authorization to the MCP caller

When `ConnectionAuthorizationRequired` is raised, the caller (or the user behind
them) hasn't connected the downstream account. Return the `connect_url` /
`connectUrl` in your tool result so the client can open it; after consent, the
same tool call succeeds.

## High-risk tools: add a CIBA approval gate

For destructive or sensitive tools, require an out-of-band approval before the
exchange — even though the caller is already authenticated to the MCP server. See
the [approval gate section](standalone-connections.md#human-in-the-loop-approval-ciba-gate)
in the standalone guide; the wiring is identical here.

## Forward-compat: execute mode

When Descope's hosted execution endpoint ships, an MCP server can flip the client
to `mode="execute"` / `mode: 'execute'` so downstream calls route through Descope —
the token never enters the server process and every call is policy-checked and
audited. The tool handler changes from "fetch a token and call" to "describe the
call and let Descope run it"; the surrounding code is unchanged. This path is
stubbed today (see the execution seam) and turns on via the `mode` flag.
