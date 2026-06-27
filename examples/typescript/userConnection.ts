/**
 * Acting for a user: fetch their Connection token (e.g. GitHub).
 *
 * A user-level Connection token can only be fetched with the user's Descope access
 * token (or a management key) — so this uses AccessTokenProvider. If the user hasn't
 * linked the account yet, getToken throws ConnectionAuthorizationRequired carrying
 * the connect URL.
 *
 *   npm run user        # tsx --env-file=../.env userConnection.ts
 */

import {
  AccessTokenProvider,
  AgentAuthClient,
  ConnectionAuthorizationRequired,
} from '@descope/agent-auth';
import { baseUrl, optional, preview, required } from './config';

async function main(): Promise<void> {
  const connection = optional('CONNECTION_NAME', 'github');
  const identifier = required('DESCOPE_USER_IDENTIFIER');

  const client = new AgentAuthClient({
    projectId: required('DESCOPE_PROJECT_ID'),
    baseUrl: baseUrl(),
    credential: new AccessTokenProvider({ accessToken: required('DESCOPE_USER_JWT') }),
  });

  try {
    const token = await client.connections.getToken({ connection, identifier });
    console.log(`Got a '${connection}' token for ${identifier}:`);
    console.log(`  accessToken = ${preview(token.accessToken)}`);
    console.log(`  scopes      = ${JSON.stringify(token.scopes)}`);
    console.log(`  expiresAt   = ${token.expiresAt}`);
  } catch (err) {
    if (err instanceof ConnectionAuthorizationRequired) {
      console.log(`'${identifier}' hasn't connected '${connection}' yet.`);
      console.log(`Send them to the connect URL to consent:\n  ${err.connectUrl}`);
      console.log('Then re-run this script — the next fetch will succeed.');
      return;
    }
    throw err;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
