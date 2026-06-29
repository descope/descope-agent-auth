/**
 * LangChain agent whose tools fetch their own credentials from Descope.
 *
 * The agent runs autonomously (client credentials, no user in the loop), and each
 * tool pulls the exact token it needs at call time:
 *
 *   - queryInternalApi -> a Descope Resource token (your own API, protected by
 *     Descope OAuth scopes), minted from the agent's identity via token-exchange.
 *   - lookupSharedCrm  -> a tenant-level Connection API key (one org-shared
 *     credential every user shares -- no per-user auth) from the Descope vault.
 *
 * The token never reaches the model: the LLM only ever sees a tool's result.
 *
 *   npm install                                   # @descope/agent-auth + tsx
 *   npm install langchain @langchain/openai @langchain/core zod
 *   export OPENAI_API_KEY=sk-...
 *   npm run langchain -- "look up Acme Corp, then check the internal API for their plan"
 */

import { createAgent } from 'langchain';
import { tool } from '@langchain/core/tools';
import { z } from 'zod';

import { AgentAuthClient, ClientCredentialsProvider } from '@descope/agent-auth';
import { baseUrl, optional, preview, required } from './config';

async function main(): Promise<void> {
  // One autonomous client for the whole agent. Client credentials can mint Resource
  // tokens (scoped to the agent) and read tenant-level Connection tokens.
  const client = new AgentAuthClient({
    projectId: required('DESCOPE_PROJECT_ID'),
    baseUrl: baseUrl(),
    credential: new ClientCredentialsProvider({
      clientId: required('DESCOPE_CLIENT_ID'),
      clientSecret: required('DESCOPE_CLIENT_SECRET'),
    }),
  });
  const resource = optional('RESOURCE', 'urn:my-api');
  const crmConnection = optional('CONNECTION_NAME', 'salesforce');
  const tenantId = required('TENANT_ID');

  const queryInternalApi = tool(
    async ({ path }) => {
      const token = await client.resources.getToken({ resource, scopes: ['read'] });
      // Real call (your internal API trusts Descope-issued OAuth tokens):
      //   await fetch(`https://internal.acme.com${path}`,
      //     { headers: { Authorization: `Bearer ${token.accessToken}` } });
      return `[demo] GET ${path} with resource token ${preview(token.accessToken)}`;
    },
    {
      name: 'query_internal_api',
      description: "Call the company's internal API at a path, e.g. '/customers/acme/plan'.",
      schema: z.object({ path: z.string().describe('API path to GET') }),
    },
  );

  const lookupSharedCrm = tool(
    async ({ company }) => {
      const token = await client.connections.getTenantToken({
        connection: crmConnection,
        tenantId,
      });
      // Real call (org-shared API key from the vault):
      //   await fetch(`https://api.crm.example/v1/accounts?q=${company}`,
      //     { headers: { Authorization: `Bearer ${token.accessToken}` } });
      return `[demo] search CRM for ${company} with org key ${preview(token.accessToken)}`;
    },
    {
      name: 'lookup_shared_crm',
      description: "Look up a company in the org's shared CRM (one org-wide connection).",
      schema: z.object({ company: z.string().describe('Company name to look up') }),
    },
  );

  const agent = createAgent({
    model: `openai:${optional('OPENAI_MODEL', 'gpt-4o-mini')}`,
    tools: [queryInternalApi, lookupSharedCrm],
    systemPrompt: 'You are an internal assistant. Use the tools to answer.',
  });

  const question = process.argv[2] ?? 'Look up Acme Corp in the CRM.';
  const result = await agent.invoke({ messages: [{ role: 'user', content: question }] });
  const last = result.messages.at(-1);
  console.log('\n=== answer ===');
  console.log(typeof last?.content === 'string' ? last.content : JSON.stringify(last?.content));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
