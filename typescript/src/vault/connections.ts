/**
 * ConnectionsClient -- the headline phase-2 operation.
 *
 * Fetch a scoped downstream provider token (GitHub, Slack, ...) from the vault
 * for a given identity. Omit `scopes` to request the Connection's configured
 * defaults; pass `scopes` to override them entirely (the SDK never clamps to a
 * subset -- the real guardrail is Policies, not the default-scope list).
 */

import { OUTBOUND_USER_TOKEN, OUTBOUND_USER_TOKEN_LATEST } from '../endpoints';
import { Execution, ToolRequest } from '../execution';
import { ApprovalRequest, VaultToken } from '../types';
import { FetchArgs } from './base';

export interface GetConnectionTokenArgs {
  connection: string;
  /** The principal the agent acts for (Descope user ID or login ID). */
  identifier: string;
  scopes?: string[];
  tenantId?: string;
  withRefreshToken?: boolean;
  forceRefresh?: boolean;
  redirectUrl?: string;
  requireApproval?: ApprovalRequest;
  /** Run this call as a specific user by presenting their Descope access token. */
  actAsUserToken?: string;
}

export interface ExecuteConnectionArgs {
  request: ToolRequest;
  connection: string;
  identifier: string;
  scopes?: string[];
  tenantId?: string;
  requireApproval?: ApprovalRequest;
  actAsUserToken?: string;
}

const cacheKey = (connection: string, identifier: string, scopes?: string[]): string => {
  const scopePart = scopes && scopes.length ? [...scopes].sort().join(',') : '<defaults>';
  return `vault:user:${connection}:${identifier}:${scopePart}`;
};

const buildArgs = (args: GetConnectionTokenArgs): FetchArgs => {
  const { connection, identifier, scopes, tenantId } = args;
  const body: Record<string, unknown> = { appId: connection, userId: identifier };
  if (tenantId) body.tenantId = tenantId;
  if (args.withRefreshToken || args.forceRefresh) {
    body.options = {
      withRefreshToken: Boolean(args.withRefreshToken),
      forceRefresh: Boolean(args.forceRefresh),
    };
  }

  // Omitted scopes -> /latest (Connection defaults); explicit scopes -> override.
  let path = OUTBOUND_USER_TOKEN_LATEST;
  if (scopes && scopes.length) {
    path = OUTBOUND_USER_TOKEN;
    body.scopes = scopes;
  }

  // The connect URL requests the SAME scopes as the token fetch, so a user who
  // hasn't connected yet consents to exactly what this tool needs. Omitting scopes
  // falls back to the Connection's configured default scopes.
  // UNVERIFIED: per-request `scopes` on the REST connect endpoint is not in the
  // public docs (the Flow "Outbound App Connect" action does support a custom-scope
  // override) -- confirm against your project; the field may need to move under
  // `options`.
  const connectBody: Record<string, unknown> = { appId: connection };
  if (tenantId) connectBody.tenantId = tenantId;
  if (scopes && scopes.length) connectBody.scopes = scopes;
  if (args.redirectUrl) connectBody.options = { redirectUrl: args.redirectUrl };

  return {
    path,
    body,
    cacheKey: cacheKey(connection, identifier, scopes),
    connection,
    identifier,
    connectBody,
    forceRefresh: Boolean(args.forceRefresh),
    requireApproval: args.requireApproval,
    actAsUserToken: args.actAsUserToken,
  };
};

export class ConnectionsClient {
  constructor(private readonly execution: Execution) {}

  /**
   * Return a currently-valid downstream token for `identifier`. Throws
   * `ConnectionAuthorizationRequired` (carrying `connectUrl`) when the user hasn't
   * connected the account yet, `PolicyDenied` when an agent token lacks policy
   * permission, `ApprovalDenied` / `ApprovalTimeout` if a `requireApproval` gate
   * fails, or `TokenExchangeFailed` otherwise.
   */
  async getToken(args: GetConnectionTokenArgs): Promise<VaultToken> {
    return this.execution.fetchToken(buildArgs(args));
  }

  /**
   * Execute-mode counterpart of `getToken` (see execution seam). Routes `request`
   * through Descope's hosted execution endpoint with the token kept vaulted.
   * Stubbed until that endpoint ships; requires `mode: 'execute'`.
   */
  async execute(args: ExecuteConnectionArgs): Promise<unknown> {
    return this.execution.execute(args.request, buildArgs(args));
  }
}
