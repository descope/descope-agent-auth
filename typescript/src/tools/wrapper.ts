/**
 * The tool wrapper (three-line ergonomic).
 *
 * A convenience layer so an AI-generated or handwritten tool gets its scoped,
 * fresh token injected without the author writing exchange logic.
 *
 *     const listRepos = withConnection(
 *       client,
 *       { connection: 'github', scopes: ['repo'] },
 *       async (token, identifier) => {
 *         const octokit = new Octokit({ auth: token });
 *         const { data } = await octokit.rest.repos.listForAuthenticatedUser();
 *         return data.map((r) => r.name);
 *       },
 *     );
 *
 *     const repos = await listRepos('user@example.com');
 *
 * The wrapper resolves the identifier (server-side, never from untrusted input),
 * fetches the scoped token via phase 2, injects it, and lets the
 * `ConnectionAuthorizationRequired` re-auth signal propagate to the caller.
 */

import { AgentAuthClient } from '../client';
import { ApprovalRequest } from '../types';

export interface WithConnectionOptions {
  connection: string;
  scopes?: string[];
  tenantId?: string;
  requireApproval?: ApprovalRequest;
}

export type ToolFn<TArgs extends unknown[], TResult> = (
  token: string,
  identifier: string,
  ...args: TArgs
) => Promise<TResult> | TResult;

/**
 * Wrap a tool `fn(token, identifier, ...args)` so the scoped Connection token is
 * fetched and injected automatically. The returned function is called as
 * `wrapped(identifier, ...args)`.
 */
export function withConnection<TArgs extends unknown[], TResult>(
  client: AgentAuthClient,
  options: WithConnectionOptions,
  fn: ToolFn<TArgs, TResult>,
): (identifier: string, ...args: TArgs) => Promise<TResult> {
  return async (identifier: string, ...args: TArgs): Promise<TResult> => {
    const token = await client.connections.getToken({
      connection: options.connection,
      identifier,
      scopes: options.scopes,
      tenantId: options.tenantId,
      requireApproval: options.requireApproval,
    });
    return fn(token.accessToken, identifier, ...args);
  };
}
