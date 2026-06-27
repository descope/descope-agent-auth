/**
 * ConnectionsClient -- the headline phase-2 operation.
 *
 * Fetch a scoped downstream provider token (GitHub, Slack, ...) from the vault
 * for a given identity. Omit `scopes` to request the Connection's configured
 * defaults; pass `scopes` to override them entirely (the SDK never clamps to a
 * subset -- the real guardrail is Policies, not the default-scope list).
 */

import {
  OUTBOUND_TENANT_TOKEN,
  OUTBOUND_TENANT_TOKEN_LATEST,
  OUTBOUND_USER_TOKEN,
  OUTBOUND_USER_TOKEN_LATEST,
} from '../endpoints';
import { AgentAuthError, ConnectionAuthorizationRequired } from '../errors';
import { sleep } from '../httpClient';
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
  /**
   * Escape hatch for extra provider-specific passthrough fields on the connect-URL
   * `options`. Does NOT bind the URL to a user -- Descope associates the connection
   * with whoever the request's bearer token identifies.
   */
  connectOptions?: Record<string, unknown>;
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
  connectOptions?: Record<string, unknown>;
  requireApproval?: ApprovalRequest;
  actAsUserToken?: string;
}

export interface GetTenantConnectionTokenArgs {
  connection: string;
  /** The tenant whose org-shared token you want. */
  tenantId: string;
  scopes?: string[];
  withRefreshToken?: boolean;
  forceRefresh?: boolean;
  requireApproval?: ApprovalRequest;
  actAsUserToken?: string;
}

export interface GetConnectUrlArgs {
  connection: string;
  /** Mirrors `getToken` for symmetry; the URL binds to the user the call authenticates as. */
  identifier: string;
  scopes?: string[];
  tenantId?: string;
  redirectUrl?: string;
  connectOptions?: Record<string, unknown>;
  actAsUserToken?: string;
}

export interface WaitForConnectionArgs extends GetConnectionTokenArgs {
  /** Seconds between polls (default 2). */
  pollIntervalSeconds?: number;
  /** Give up and throw after this many seconds (default 300). */
  timeoutSeconds?: number;
}

const cacheKey = (
  connection: string,
  identifier: string,
  scopes?: string[],
  tenantId?: string,
): string => {
  // tenantId is part of the key: one Connection can hold several user tokens for
  // the same user, one per tenant, and they are NOT interchangeable.
  const scopePart = scopes && scopes.length ? [...scopes].sort().join(',') : '<defaults>';
  return `vault:user:${connection}:${identifier}:${tenantId ?? '<none>'}:${scopePart}`;
};

const tenantCacheKey = (connection: string, tenantId: string, scopes?: string[]): string => {
  const scopePart = scopes && scopes.length ? [...scopes].sort().join(',') : '<defaults>';
  return `vault:tenant:${connection}:${tenantId}:${scopePart}`;
};

const buildConnectBody = (args: {
  connection: string;
  tenantId?: string;
  scopes?: string[];
  redirectUrl?: string;
  connectOptions?: Record<string, unknown>;
}): Record<string, unknown> => {
  // The call's scopes + redirectUrl, plus any extra provider-specific passthrough
  // fields from connectOptions.
  const options: Record<string, unknown> = { ...(args.connectOptions ?? {}) };
  if (args.redirectUrl) options.redirectUrl = args.redirectUrl;
  if (args.scopes && args.scopes.length) options.scopes = args.scopes;
  const connectBody: Record<string, unknown> = { appId: args.connection };
  if (args.tenantId) connectBody.tenantId = args.tenantId;
  if (Object.keys(options).length > 0) connectBody.options = options;
  return connectBody;
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

  const connectBody = buildConnectBody({
    connection,
    tenantId,
    scopes,
    redirectUrl: args.redirectUrl,
    connectOptions: args.connectOptions,
  });

  return {
    path,
    body,
    cacheKey: cacheKey(connection, identifier, scopes, tenantId),
    connection,
    identifier,
    connectBody,
    forceRefresh: Boolean(args.forceRefresh),
    requireApproval: args.requireApproval,
    actAsUserToken: args.actAsUserToken,
  };
};

const buildTenantArgs = (args: GetTenantConnectionTokenArgs): FetchArgs => {
  const { connection, tenantId, scopes } = args;
  const body: Record<string, unknown> = { appId: connection, tenantId };
  if (args.withRefreshToken || args.forceRefresh) {
    body.options = {
      withRefreshToken: Boolean(args.withRefreshToken),
      forceRefresh: Boolean(args.forceRefresh),
    };
  }

  let path = OUTBOUND_TENANT_TOKEN_LATEST;
  if (scopes && scopes.length) {
    path = OUTBOUND_TENANT_TOKEN;
    body.scopes = scopes;
  }

  // No connectBody: a tenant-level Connection token is admin/IaC-provisioned (a
  // shared org credential), not minted by a per-user OAuth consent, so there is no
  // connect URL to build on a miss.
  return {
    path,
    body,
    cacheKey: tenantCacheKey(connection, tenantId, scopes),
    connection,
    connectBody: undefined,
    forceRefresh: Boolean(args.forceRefresh),
    requireApproval: args.requireApproval,
    actAsUserToken: args.actAsUserToken,
  };
};

export class ConnectionsClient {
  constructor(private readonly execution: Execution) {}

  /**
   * Return a currently-valid **user-level** downstream token for `identifier`.
   *
   * `tenantId` selects which of a user's tokens to fetch: one Connection can hold
   * several tokens for the same user, one per tenant. Omit it for the user's
   * tenant-less token; pass it for the tenant-bound one. They are distinct — asking
   * for a tenant-bound token *without* its `tenantId` reads as "not connected". For
   * an org-shared token not tied to a user, use `getTenantToken`.
   *
   * Throws `ConnectionAuthorizationRequired` (carrying `connectUrl`) when the user
   * hasn't connected the account yet, `PolicyDenied` when an agent token lacks
   * policy permission, `ApprovalDenied` / `ApprovalTimeout` if a `requireApproval`
   * gate fails, or `TokenExchangeFailed` otherwise.
   */
  async getToken(args: GetConnectionTokenArgs): Promise<VaultToken> {
    return this.execution.fetchToken(buildArgs(args));
  }

  /**
   * Return a currently-valid **tenant-level** downstream token — a single
   * credential shared by a whole tenant/organization, keyed by `tenantId` with no
   * user. Because it isn't tied to a user, this is the one Connection fetch an
   * autonomous agent (client-credentials, no user token) can perform, provided its
   * identity is associated with the tenant.
   *
   * There is no connect-URL fallback (a tenant token is admin/IaC-provisioned, not
   * minted by a per-user consent); a miss throws `ConnectionAuthorizationRequired`
   * with no `connectUrl`.
   */
  async getTenantToken(args: GetTenantConnectionTokenArgs): Promise<VaultToken> {
    return this.execution.fetchToken(buildTenantArgs(args));
  }

  /**
   * Generate the URL to send a user through to authorize this Connection — the
   * proactive counterpart of catching `ConnectionAuthorizationRequired`. Call it
   * when you want to start the "Connect <provider>" flow yourself (a button, a
   * redirect). Hand the returned URL to the user; once they complete the provider's
   * OAuth consent, Descope stores the token and `getToken` succeeds.
   *
   * The URL is tied to the user the call authenticates as, so present that user's
   * token via `actAsUserToken` (or configure the client with it).
   */
  async getConnectUrl(args: GetConnectUrlArgs): Promise<string | undefined> {
    const connectBody = buildConnectBody({
      connection: args.connection,
      tenantId: args.tenantId,
      scopes: args.scopes,
      redirectUrl: args.redirectUrl,
      connectOptions: args.connectOptions,
    });
    return this.execution.getConnectUrl(connectBody, args.actAsUserToken);
  }

  /**
   * Poll `getToken` until the user finishes connecting, then resolve with the token.
   *
   * Use after you've sent the user to the connect URL (see `getConnectUrl`): this
   * re-fetches until the vault holds the token. Rejects with `AgentAuthError` if
   * `timeoutSeconds` elapse first.
   */
  async waitForConnection(args: WaitForConnectionArgs): Promise<VaultToken> {
    const { pollIntervalSeconds, timeoutSeconds, ...tokenArgs } = args;
    const pollMs = (pollIntervalSeconds ?? 2) * 1000;
    const deadline = Date.now() + (timeoutSeconds ?? 300) * 1000;
    for (;;) {
      try {
        // eslint-disable-next-line no-await-in-loop
        return await this.getToken({ ...tokenArgs, forceRefresh: true });
      } catch (err) {
        if (!(err instanceof ConnectionAuthorizationRequired)) throw err;
        const remaining = deadline - Date.now();
        if (remaining <= 0) {
          throw new AgentAuthError(
            `timed out after ${timeoutSeconds ?? 300}s waiting for '${args.identifier}' ` +
              `to connect '${args.connection}'`,
          );
        }
        // eslint-disable-next-line no-await-in-loop
        await sleep(Math.min(pollMs, remaining));
      }
    }
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
