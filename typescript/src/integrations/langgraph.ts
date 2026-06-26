/**
 * LangGraph integration: turn re-auth / approval signals into `interrupt()`s.
 *
 * A thin, optional helper. The core `withConnection` already drops a scoped token
 * into any tool; this variant additionally catches the SDK's re-auth / approval
 * exceptions and converts them into a LangGraph `interrupt()`, so the graph pauses
 * for the human (e.g. to complete an OAuth connect) and retries automatically on
 * resume.
 *
 * The SDK never depends on LangGraph: you pass `interrupt` in (import it from
 * `@langchain/langgraph`). That keeps the package dependency-free and edge-safe,
 * and makes the helper trivially testable.
 *
 *     import { interrupt } from '@langchain/langgraph';
 *     import { langgraphConnectionTool } from '@descope/agent-auth';
 *
 *     const listRepos = langgraphConnectionTool(
 *       client,
 *       { connection: 'github', scopes: ['repo'], interrupt },
 *       async (token, identifier) => new Octokit({ auth: token }).rest.repos.listForAuthenticatedUser(),
 *     );
 */

import type { AgentAuthClient } from '../client';
import {
  AgentAuthError,
  ApprovalDenied,
  ApprovalTimeout,
  ConnectionAuthorizationRequired,
} from '../errors';
import type { ApprovalRequest } from '../types';

/** LangGraph's `interrupt`: pauses the graph (throws) and returns the resume value. */
export type InterruptFn = (value: unknown) => unknown;

export interface LangGraphConnectionOptions {
  connection: string;
  scopes?: string[];
  tenantId?: string;
  requireApproval?: ApprovalRequest;
  /** LangGraph's `interrupt` function (from `@langchain/langgraph`). */
  interrupt: InterruptFn;
  /** Also interrupt (and retry) on ApprovalDenied / ApprovalTimeout. Default: false. */
  alsoInterruptOnApproval?: boolean;
}

/** Build the structured value handed to `interrupt()` for a given SDK error. */
export function interruptPayload(err: AgentAuthError): Record<string, unknown> {
  if (err instanceof ConnectionAuthorizationRequired) {
    return {
      type: 'connection_authorization_required',
      connection: err.connection,
      identifier: err.identifier,
      connectUrl: err.connectUrl,
      message: err.message,
    };
  }
  if (err instanceof ApprovalDenied) return { type: 'approval_denied', message: err.message };
  if (err instanceof ApprovalTimeout) return { type: 'approval_timeout', message: err.message };
  return { type: 'error', message: err.message };
}

/**
 * LangGraph-aware variant of `withConnection`. Fetches the scoped Connection token
 * and, on a re-auth (or — when enabled — approval) error, calls `interrupt(payload)`
 * so the graph pauses, retrying the exchange on resume.
 */
export function langgraphConnectionTool<TArgs extends unknown[], TResult>(
  client: AgentAuthClient,
  options: LangGraphConnectionOptions,
  fn: (token: string, identifier: string, ...args: TArgs) => Promise<TResult> | TResult,
): (identifier: string, ...args: TArgs) => Promise<TResult> {
  return async (identifier: string, ...args: TArgs): Promise<TResult> => {
    for (;;) {
      try {
        // eslint-disable-next-line no-await-in-loop
        const token = await client.connections.getToken({
          connection: options.connection,
          identifier,
          scopes: options.scopes,
          tenantId: options.tenantId,
          requireApproval: options.requireApproval,
        });
        // eslint-disable-next-line no-await-in-loop
        return await fn(token.accessToken, identifier, ...args);
      } catch (err) {
        const isConn = err instanceof ConnectionAuthorizationRequired;
        const isApproval = err instanceof ApprovalDenied || err instanceof ApprovalTimeout;
        if (isConn || (options.alsoInterruptOnApproval && isApproval)) {
          // On the first pass LangGraph's interrupt() throws to pause the graph; on
          // resume the node re-runs and the loop retries the exchange.
          options.interrupt(interruptPayload(err as AgentAuthError));
          // eslint-disable-next-line no-continue
          continue;
        }
        throw err;
      }
    }
  };
}
