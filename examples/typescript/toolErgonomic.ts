/**
 * The three-line tool ergonomic: withConnection injects a fresh, scoped token.
 *
 * You write a tool as `(token, identifier, ...) => ...`; the wrapper fetches the
 * Connection token for that identity and passes it in. The
 * ConnectionAuthorizationRequired re-auth signal still propagates.
 *
 *   npm run tool   # tsx --env-file=../.env toolErgonomic.ts
 */

import {
  AccessTokenProvider,
  AgentAuthClient,
  ConnectionAuthorizationRequired,
  withConnection,
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

  // The tool body never touches exchange logic — it just receives `token`.
  const whoami = withConnection(client, { connection }, async (token: string, id: string) => {
    // A real tool would call the provider's API with `token` here.
    return `would call '${connection}' as ${id} with ${preview(token)}`;
  });

  try {
    console.log(await whoami(identifier));
  } catch (err) {
    if (err instanceof ConnectionAuthorizationRequired) {
      console.log(`Connect '${connection}' first: ${err.connectUrl}`);
      return;
    }
    throw err;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
