/**
 * Autonomous agent (client credentials, no user in the loop).
 *
 * The two token kinds an M2M agent can obtain:
 *   1. a Resource token (token-exchange, scoped to the agent itself), and
 *   2. a tenant-level Connection token (org-shared, no user) — if the agent's
 *      identity is associated with that tenant.
 * It cannot fetch a user's Connection token; that needs the user's token
 * (see userConnection.ts).
 *
 *   npm run autonomous   # tsx --env-file=../.env autonomousAgent.ts
 */

import {
  AgentAuthClient,
  ClientCredentialsProvider,
  ConnectionAuthorizationRequired,
} from '@descope/agent-auth';
import { baseUrl, optional, preview, required } from './config';

async function main(): Promise<void> {
  const client = new AgentAuthClient({
    projectId: required('DESCOPE_PROJECT_ID'),
    baseUrl: baseUrl(),
    credential: new ClientCredentialsProvider({
      clientId: required('DESCOPE_CLIENT_ID'),
      clientSecret: required('DESCOPE_CLIENT_SECRET'),
    }),
  });

  // 1. Resource token — minted from the agent's own identity.
  const resource = optional('RESOURCE', 'urn:my-api');
  const res = await client.resources.getToken({ resource, scopes: ['read'] });
  console.log(`Resource token for '${resource}':`);
  console.log(`  accessToken = ${preview(res.accessToken)}  scopes=${JSON.stringify(res.scopes)}`);

  // 2. Tenant-level Connection token — org-shared, keyed by tenant (no user).
  const tenantId = process.env.TENANT_ID;
  if (!tenantId) {
    console.log('\nSet TENANT_ID to also try a tenant-level Connection token.');
    return;
  }

  const connection = optional('CONNECTION_NAME', 'slack');
  try {
    const tok = await client.connections.getTenantToken({ connection, tenantId });
    console.log(`\nTenant token for '${connection}' / tenant '${tenantId}':`);
    console.log(`  accessToken = ${preview(tok.accessToken)}  scopes=${JSON.stringify(tok.scopes)}`);
  } catch (err) {
    if (err instanceof ConnectionAuthorizationRequired) {
      console.log(`\nNo tenant-level '${connection}' token provisioned for tenant '${tenantId}'.`);
      console.log('Provision one in the Descope Console / Management API first.');
      return;
    }
    throw err;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
