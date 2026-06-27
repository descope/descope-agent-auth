/**
 * Shared phase-2 exchange machinery.
 *
 * Both ConnectionsClient and ResourcesClient consume whatever phase-1 credential
 * the client holds, build the management-style bearer header
 * (`Bearer <projectId>:<credential>`), call an outbound token endpoint, and map
 * the result -- including the headline 404 -> ConnectionAuthorizationRequired path.
 */

import { OUTBOUND_CONNECT } from '../endpoints';
import {
  AgentAuthError,
  ConnectionAuthorizationRequired,
  PolicyDenied,
  TokenExchangeFailed,
} from '../errors';
import { HttpClient } from '../httpClient';
import { TokenStore } from '../store/base';
import { ApprovalRequest, Credential, VaultToken, vaultTokenExpired } from '../types';

export type ApprovalGate = (request: ApprovalRequest) => Promise<void>;

/** Map Descope's accessTokenExpiry (epoch number or RFC3339 string) to unix seconds. */
export const parseExpiry = (value: unknown): number | undefined => {
  if (value === null || value === undefined) return undefined;
  if (typeof value === 'number') {
    return value > 1e12 ? value / 1000 : value;
  }
  if (typeof value === 'string') {
    const v = value.trim();
    if (!v) return undefined;
    const num = Number(v);
    if (!Number.isNaN(num)) return num > 1e12 ? num / 1000 : num;
    const ms = Date.parse(v);
    return Number.isNaN(ms) ? undefined : ms / 1000;
  }
  return undefined;
};

export const tokenObjectToVaultToken = (obj: Record<string, any>): VaultToken => {
  const raw: Record<string, unknown> = {};
  Object.entries(obj).forEach(([k, v]) => {
    if (k !== 'accessToken' && k !== 'refreshToken') raw[k] = v;
  });
  return {
    accessToken: String(obj.accessToken ?? ''),
    tokenType: obj.accessTokenType || 'Bearer',
    expiresAt: parseExpiry(obj.accessTokenExpiry),
    scopes: Array.isArray(obj.scopes) ? obj.scopes : [],
    refreshToken: obj.refreshToken,
    hasRefreshToken: Boolean(obj.hasRefreshToken),
    appId: obj.appId,
    userId: obj.userId,
    raw,
  };
};

export interface FetchArgs {
  path: string;
  body: Record<string, unknown>;
  cacheKey: string;
  connection: string;
  identifier?: string;
  connectBody?: Record<string, unknown>;
  forceRefresh: boolean;
  requireApproval?: ApprovalRequest;
  actAsUserToken?: string;
}

export class VaultBackend {
  constructor(
    private readonly http: HttpClient,
    private readonly projectId: string,
    private readonly getCredential: () => Promise<Credential>,
    private readonly store: TokenStore,
    private readonly approvalGate?: ApprovalGate,
    private readonly skewSeconds = 60,
    // When false, never read/write the phase-2 token cache: every fetch hits
    // Descope, so Policies are re-enforced on every call (a cached token skips the
    // retrieval-time policy check until it expires).
    private readonly cacheTokens = true,
  ) {}

  private async authHeader(): Promise<string> {
    const cred = await this.getCredential();
    return `Bearer ${this.projectId}:${cred.token}`;
  }

  private async cacheGet(cacheKey: string): Promise<VaultToken | undefined> {
    const rawStr = await this.store.get(cacheKey);
    if (!rawStr) return undefined;
    let obj: Record<string, any>;
    try {
      obj = JSON.parse(rawStr);
    } catch {
      return undefined;
    }
    const token = tokenObjectToVaultToken(obj);
    if (vaultTokenExpired(token, this.skewSeconds)) {
      await this.store.delete(cacheKey);
      return undefined;
    }
    return token;
  }

  private async cacheSet(cacheKey: string, token: VaultToken): Promise<void> {
    const payload: Record<string, unknown> = {
      ...(token.raw ?? {}),
      accessToken: token.accessToken,
    };
    const ttl =
      token.expiresAt !== undefined ? Math.max(0, token.expiresAt - Date.now() / 1000) : undefined;
    await this.store.set(cacheKey, JSON.stringify(payload), ttl);
  }

  async fetch(args: FetchArgs): Promise<VaultToken> {
    // Phase-2 CIBA gate: a real person must sign off before this sensitive
    // exchange proceeds. Runs before any cache hit so the approval is never
    // skipped for a cached token.
    if (args.requireApproval) {
      if (!this.approvalGate) {
        throw new AgentAuthError(
          'requireApproval was set but no approval provider is configured on the client; ' +
            'pass approval: new CibaProvider(...) to AgentAuthClient',
        );
      }
      await this.approvalGate(args.requireApproval);
    }

    if (this.cacheTokens && !args.forceRefresh) {
      const cached = await this.cacheGet(args.cacheKey);
      if (cached) return cached;
    }

    // actAsUserToken: present a specific user's Descope access token for this call
    // so the vault fetch is user-scoped, instead of the client's credential.
    const header = args.actAsUserToken
      ? `Bearer ${this.projectId}:${args.actAsUserToken}`
      : await this.authHeader();
    const resp = await this.http.postJson(args.path, args.body, { Authorization: header });

    if (resp.ok && resp.json?.token) {
      const token = tokenObjectToVaultToken(resp.json.token);
      if (this.cacheTokens) await this.cacheSet(args.cacheKey, token);
      return token;
    }

    // 404 -> user has not connected (or token cleared / wrong scopes).
    if (resp.statusCode === 404) {
      const connectUrl = await this.tryConnectUrl(args.connectBody, header);
      throw new ConnectionAuthorizationRequired(
        `connection '${args.connection}' is not authorized for this identity yet`,
        { connectUrl, connection: args.connection, identifier: args.identifier },
      );
    }

    // 401/403 -> Policy (or auth) denied. Meaningful for agent tokens;
    // a management key is unrestricted, so a 403 there is a real config error.
    if (resp.statusCode === 401 || resp.statusCode === 403) {
      throw new PolicyDenied(
        `policy denied for connection '${args.connection}' ` +
          `(${resp.statusCode}): ${msg(resp.json) ?? resp.text}`,
        { connection: args.connection, scopes: args.body.scopes as string[] | undefined },
      );
    }

    throw new TokenExchangeFailed(
      `token exchange failed (${resp.statusCode}): ${msg(resp.json) ?? resp.text}`,
      { statusCode: resp.statusCode },
    );
  }

  /** Proactively generate a connect URL (the explicit authorize path). */
  async getConnectUrl(
    connectBody: Record<string, unknown> | undefined,
    actAsUserToken?: string,
  ): Promise<string | undefined> {
    if (!connectBody) return undefined;
    const header = actAsUserToken
      ? `Bearer ${this.projectId}:${actAsUserToken}`
      : await this.authHeader();
    return this.tryConnectUrl(connectBody, header);
  }

  private async tryConnectUrl(
    connectBody: Record<string, unknown> | undefined,
    header: string,
  ): Promise<string | undefined> {
    if (!connectBody) return undefined;
    try {
      const resp = await this.http.postJson(OUTBOUND_CONNECT, connectBody, {
        Authorization: header,
      });
      if (resp.ok && resp.json) return resp.json.url;
    } catch (err) {
      if (err instanceof AgentAuthError) return undefined;
      throw err;
    }
    return undefined;
  }
}

function msg(body: any): string | undefined {
  if (!body) return undefined;
  return body.errorDescription || body.error || body.message;
}
