/**
 * ResourcesClient -- fetch a Resource token for the project.
 *
 * Same ergonomic as ConnectionsClient. Resource tokens are tenant/resource-scoped
 * rather than per-user, so this maps onto the outbound tenant-token endpoints.
 *
 * NOTE: the precise Descope "resource token" wire mapping is the least-pinned
 * part of the spec; this targets the tenant-token endpoints and should be
 * confirmed against the API reference (see `endpoints` UNVERIFIED notes).
 */

import { OUTBOUND_TENANT_TOKEN, OUTBOUND_TENANT_TOKEN_LATEST } from '../endpoints';
import { Execution } from '../execution';
import { ApprovalRequest, VaultToken } from '../types';

export interface GetResourceTokenArgs {
  resource: string;
  scopes?: string[];
  tenantId?: string;
  withRefreshToken?: boolean;
  forceRefresh?: boolean;
  requireApproval?: ApprovalRequest;
}

const cacheKey = (resource: string, tenantId?: string, scopes?: string[]): string => {
  const scopePart = scopes && scopes.length ? [...scopes].sort().join(',') : '<defaults>';
  return `vault:resource:${resource}:${tenantId ?? '-'}:${scopePart}`;
};

export class ResourcesClient {
  constructor(private readonly execution: Execution) {}

  async getToken(args: GetResourceTokenArgs): Promise<VaultToken> {
    const { resource, scopes, tenantId } = args;
    const body: Record<string, unknown> = { appId: resource };
    if (tenantId) body.tenantId = tenantId;
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

    return this.execution.fetchToken({
      path,
      body,
      cacheKey: cacheKey(resource, tenantId, scopes),
      connection: resource,
      connectBody: undefined, // resource tokens have no user-consent connect URL
      forceRefresh: Boolean(args.forceRefresh),
      requireApproval: args.requireApproval,
    });
  }
}
