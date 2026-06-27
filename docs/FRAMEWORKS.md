# Framework cookbook

## What this SDK is for

`descope-agent-auth` is for **homegrown / custom-built agents** — agents you write
yourself in any framework. It manages the tokens the **tools you implement** need to
call downstream APIs (the **OAuth client** side): it acquires a Descope credential
and exchanges it for Connection / Resource tokens from the Descope vault.

It does **not** manage the OAuth between your agent and a **third-party MCP server**
— when your agent is an MCP *client*, your MCP client / agent platform (AWS Bedrock
AgentCore, Azure AI Foundry, the MCP SDK's client) owns that connection's auth. Use
this SDK inside your own tool code (a Bedrock action-group Lambda, an Azure function
tool, a native framework tool) to fetch downstream tokens; a managed agent that only
orchestrates third-party MCP servers has no place to plug it in.

It is **not** a tool for building MCP servers. Protecting an MCP server (DCR,
metadata endpoints, token validation, `tools/list` filtering) is the
*resource-server* side — for that, use Descope's MCP server SDKs
([`@descope/mcp-express`](https://docs.descope.com/mcp/mcp-express-sdk) or the
[`descope-mcp` Python SDK](https://docs.descope.com/mcp/python-sdk)). This SDK is
the *client* side, and the two are complementary: inside an MCP server's tool
handler, use this SDK to fetch the downstream token the tool needs (resolve the
user from the validated request, then call `connections.get_token` /
`resources.get_token`).

## Do you need a separate SDK per framework?

**No.** Rather than shipping one package per framework, this is **one
framework-agnostic core SDK**. Here's why that's enough:

- Every framework below defines a "tool" as **just a function**.
- The SDK's job is to hand that function a fresh, correctly-scoped token. The
  `with_connection` / `withConnection` wrapper (or a direct
  `client.connections.get_token(...)` call) does exactly that **inside any tool
  body**, regardless of framework.
- The only framework-specific concern is how you surface a *re-authorization* or
  *approval* interrupt back to the user — and that's a `try/except` around the
  exchange, shown once below and reused everywhere.

So there is nothing to install per framework. Pick your phase-1 provider, build one
client, and drop the wrapper into your tools.

### Runtime support

The SDK runs on **Node, Cloudflare Workers, Deno, Bun, and browsers** — it uses
only universal Web primitives (`fetch`, WebCrypto, `btoa`), so it works on edge
runtimes without `nodejs_compat` for the auth layer.

---

## The one pattern

A tool is a function. Resolve the **identifier server-side** (from your session /
agent context — never from model-supplied input), fetch the scoped token, use it.

**Python**

```python
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):
    return GitHub(auth=token).repos.list_for_authenticated_user()
```

**TypeScript**

```ts
import { withConnection } from '@descope/agent-auth';

const listRepos = withConnection(
  client,
  { connection: 'github', scopes: ['repo'] },
  async (token, identifier) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser(),
);
```

### Handling the re-auth interrupt (works in every framework)

```python
from descope_agent_auth.errors import ConnectionAuthorizationRequired

try:
    repos = list_repos(identifier=current_user_id)
except ConnectionAuthorizationRequired as e:
    return f"Please connect GitHub first: {e.connect_url}"
```

```ts
import { ConnectionAuthorizationRequired } from '@descope/agent-auth';

try {
  await listRepos(currentUserId);
} catch (e) {
  if (e instanceof ConnectionAuthorizationRequired) return `Connect GitHub first: ${e.connectUrl}`;
  throw e;
}
```

> The snippets below show only the integration point — the tool's function body. The
> `client` is the `AgentAuthClient` you built once at startup, and `identifier` is
> resolved from your app's session/context. Adapt each to the framework's current
> tool API.

---

## LangChain

**Python** (`@tool` decorator):

```python
from langchain_core.tools import tool
from descope_agent_auth import with_connection

@tool
def list_repos(identifier: str) -> list[str]:
    """List the user's GitHub repos."""
    fetch = with_connection(client, connection="github", scopes=["repo"])(
        lambda token, ident: [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]
    )
    return fetch(identifier=identifier)
```

**JS/TS** (`tool` from `@langchain/core/tools`):

```ts
import { tool } from '@langchain/core/tools';
import { z } from 'zod';
import { withConnection } from '@descope/agent-auth';

const listRepos = tool(
  async ({ identifier }) => {
    const run = withConnection(client, { connection: 'github', scopes: ['repo'] },
      async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());
    return (await run(identifier)).data.map((r) => r.name);
  },
  { name: 'list_repos', schema: z.object({ identifier: z.string() }) },
);
```

## LangGraph

LangGraph adds first-class **interrupts** — the natural home for the re-auth /
approval signal. There's an optional helper that wires this for you: it runs the
exchange, converts `ConnectionAuthorizationRequired` into a LangGraph `interrupt()`
(carrying the connect URL), pauses the graph, and **retries automatically on
resume**. The SDK never depends on LangGraph — you pass `interrupt` in.

**Python** (`descope-agent-auth[langgraph]`):

```python
from descope_agent_auth.integrations.langgraph import connection_tool

@connection_tool(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):
    """List the user's GitHub repos."""
    return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]
```

`connection_tool` resolves `langgraph.types.interrupt` lazily (only when an
interrupt actually fires). Pass `interrupt=...` to inject your own, and
`interrupt_on=(...)` to also pause on `ApprovalDenied` / `ApprovalTimeout`.

**TypeScript** (inject `interrupt` from `@langchain/langgraph`):

```ts
import { interrupt } from '@langchain/langgraph';
import { langgraphConnectionTool } from '@descope/agent-auth';

const listRepos = langgraphConnectionTool(
  client,
  { connection: 'github', scopes: ['repo'], interrupt }, // alsoInterruptOnApproval?: true
  async (token, identifier) =>
    (await new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser()).data.map((r) => r.name),
);
```

On resume (`Command(resume=...)`) the tool retries the exchange. To gate a
high-risk step on approval too, add `require_approval` / `requireApproval` and the
helper will interrupt on the approval errors when you opt in.

> Prefer to wire it yourself? The helper is a thin loop — catch
> `ConnectionAuthorizationRequired`, call `interrupt({...connect_url})`, and retry —
> so you can inline that in a plain `@tool` instead.

## Google ADK

ADK tools are plain Python functions handed to an `Agent`:

```python
from google.adk.agents import Agent
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):
    """List the user's GitHub repos."""
    return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]

agent = Agent(name="dev_agent", model="gemini-2.0-flash", tools=[list_repos])
```

## Anthropic SDK (tool use)

You define tools as JSON schema and implement a dispatcher. Wrap the handler:

```python
from anthropic import Anthropic
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def _list_repos(token, identifier):
    return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]

def handle_tool_use(block, identifier):  # identifier from your session, not the model
    if block.name == "list_repos":
        return _list_repos(identifier=identifier)
```

```ts
// TypeScript: same idea inside your tool-use dispatch
import Anthropic from '@anthropic-ai/sdk';
import { withConnection } from '@descope/agent-auth';

const listRepos = withConnection(client, { connection: 'github', scopes: ['repo'] },
  async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());

async function handleToolUse(block, identifier) {
  if (block.name === 'list_repos') return (await listRepos(identifier)).data;
}
```

## OpenAI Agents SDK

**Python** (`function_tool`):

```python
from agents import function_tool
from descope_agent_auth import with_connection

@function_tool
def list_repos(identifier: str) -> list[str]:
    run = with_connection(client, connection="github", scopes=["repo"])(
        lambda token, ident: [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]
    )
    return run(identifier=identifier)
```

**TS** (`tool` from `@openai/agents`):

```ts
import { tool } from '@openai/agents';
import { z } from 'zod';
import { withConnection } from '@descope/agent-auth';

const listRepos = tool({
  name: 'list_repos',
  parameters: z.object({ identifier: z.string() }),
  execute: async ({ identifier }) => {
    const run = withConnection(client, { connection: 'github', scopes: ['repo'] },
      async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());
    return (await run(identifier)).data.map((r) => r.name);
  },
});
```

## Vercel AI SDK

```ts
import { tool } from 'ai';
import { z } from 'zod';
import { withConnection } from '@descope/agent-auth';

export const listRepos = tool({
  description: "List the user's GitHub repos",
  parameters: z.object({ identifier: z.string() }),
  execute: async ({ identifier }) => {
    const run = withConnection(client, { connection: 'github', scopes: ['repo'] },
      async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());
    return (await run(identifier)).data.map((r) => r.name);
  },
});
```

## Mastra

```ts
import { createTool } from '@mastra/core/tools';
import { z } from 'zod';
import { withConnection } from '@descope/agent-auth';

export const listRepos = createTool({
  id: 'list-repos',
  description: "List the user's GitHub repos",
  inputSchema: z.object({ identifier: z.string() }),
  execute: async ({ context }) => {
    const run = withConnection(client, { connection: 'github', scopes: ['repo'] },
      async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());
    return (await run(context.identifier)).data.map((r) => r.name);
  },
});
```

## LlamaIndex

**Python** (`FunctionTool`):

```python
from llama_index.core.tools import FunctionTool
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):
    """List the user's GitHub repos."""
    return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]

tool = FunctionTool.from_defaults(fn=list_repos)
```

**TS** (`FunctionTool`):

```ts
import { FunctionTool } from 'llamaindex';
import { withConnection } from '@descope/agent-auth';

const listRepos = FunctionTool.from(
  async ({ identifier }: { identifier: string }) => {
    const run = withConnection(client, { connection: 'github', scopes: ['repo'] },
      async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());
    return (await run(identifier)).data.map((r) => r.name);
  },
  { name: 'list_repos', description: "List the user's repos", parameters: /* zod/json schema */ {} },
);
```

## Cloudflare Agents

Runs on Workers — the SDK uses WebCrypto, so no `nodejs_compat` flag is required
for the auth layer. Tools are typically Vercel-AI-SDK `tool()`s inside your `Agent`:

```ts
import { Agent } from 'agents';
import { tool } from 'ai';
import { z } from 'zod';
import { AgentAuthClient, ClientCredentialsProvider, withConnection } from '@descope/agent-auth';

export class DevAgent extends Agent {
  private auth = new AgentAuthClient({
    projectId: 'P2abc...',
    credential: new ClientCredentialsProvider({ clientId: env.CID, clientSecret: env.CSECRET }),
  });

  tools = {
    listRepos: tool({
      parameters: z.object({ identifier: z.string() }),
      execute: async ({ identifier }) => {
        const run = withConnection(this.auth, { connection: 'github', scopes: ['repo'] },
          async (token) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser());
        return (await run(identifier)).data.map((r) => r.name);
      },
    }),
  };
}
```

## Claude Managed Agents

Managed agents execute tools through your backend (a function/webhook the platform
calls, or an MCP server). Wrap that handler exactly like the Anthropic SDK example
above — resolve the identifier from the authenticated request, then call the
wrapped tool. (To make that backend an OAuth-protected MCP server, use Descope's
[MCP server SDKs](https://docs.descope.com/mcp).)

## AG2 (AutoGen)

AG2 tools are Python functions registered with an agent. Wrap the function, then
register it for the LLM (description) and the executor (execution):

```python
from autogen import ConversableAgent, register_function
from descope_agent_auth import with_connection

@with_connection(client, connection="github", scopes=["repo"])
def list_repos(token, identifier):
    """List the user's GitHub repos."""
    return [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]

register_function(
    list_repos,
    caller=assistant,        # the LLM-driven agent
    executor=user_proxy,     # the agent that runs the tool
    name="list_repos",
    description="List the user's GitHub repos",
)
# identifier is resolved server-side and supplied when the tool is invoked,
# not chosen by the model.
```

## CrewAI

CrewAI tools use the `@tool` decorator (or a `BaseTool` subclass):

```python
from crewai.tools import tool
from descope_agent_auth import with_connection
from descope_agent_auth.errors import ConnectionAuthorizationRequired

@tool("List Repos")
def list_repos(identifier: str) -> list[str]:
    """List the user's GitHub repos."""
    run = with_connection(client, connection="github", scopes=["repo"])(
        lambda token, ident: [r.name for r in GitHub(auth=token).repos.list_for_authenticated_user()]
    )
    try:
        return run(identifier=identifier)
    except ConnectionAuthorizationRequired as e:
        return f"GitHub not connected — visit {e.connect_url} to authorize."
```

## TanStack AI

A TS function-tool framework — same pattern as Vercel AI / Mastra. Define the tool
and wrap its handler with `withConnection`:

```ts
import { withConnection } from '@descope/agent-auth';

// Inside your TanStack AI tool definition's handler/execute function:
const listReposHandler = withConnection(
  client,
  { connection: 'github', scopes: ['repo'] },
  async (token, identifier) =>
    (await new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser()).data.map((r) => r.name),
);

// e.g. tool({ name: 'list_repos', inputSchema, handler: ({ identifier }) => listReposHandler(identifier) })
```

> Adapt the wrapper call to TanStack AI's current tool API; the integration point
> is always the tool's handler/`execute` function, with `identifier` resolved from
> your session — never from model input.

## OpenClaw (and any other function-tool framework)

Any framework whose tools are functions works with the same pattern — there is no
framework-specific SDK to install. Define your tool, and inside its body call the
`with_connection` / `withConnection` wrapper (or `client.connections.get_token`
directly). Resolve `identifier` from your session/agent context, and let
`ConnectionAuthorizationRequired` propagate so the user can connect the account.
Adapt the wrapper call to whatever shape the framework's tool function expects.

---

## High-risk tools: require approval

Any of the above can gate a sensitive call on a fresh out-of-band user approval
(CIBA) by configuring `approval=` / `approval:` on the client and passing
`require_approval` / `requireApproval` to the exchange — see the
[approval gate section](standalone-connections.md#human-in-the-loop-approval-ciba-gate).
