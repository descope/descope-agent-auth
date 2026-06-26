/**
 * ResourcesClient -- fetch a Descope **Resource** token.
 *
 * A Resource is an API you build and protect with Descope acting as the OAuth
 * authorization server. Unlike a Connection token (a stored API key / provider
 * OAuth token pulled from the vault), a Resource token is minted on the fly by
 * **exchanging** the agent's Descope access token for a Resource-scoped token using
 * the RFC 8693 **token-exchange** grant against the OAuth token endpoint.
 *
 * Because token-exchange needs an OAuth subject token, this requires an OAuth agent
 * identity (Client ID/Secret via any phase-1 provider). It does not apply to a
 * Management Key.
 *
 * NOTE: the exact token-exchange parameters (`resource` vs `audience`, whether
 * client auth is also required) should be confirmed against the Descope API
 * reference; the grant + endpoint are pinned in `endpoints`.
 */

import { GRANT_TOKEN_EXCHANGE, OAUTH2_TOKEN, TOKEN_TYPE_ACCESS_TOKEN } from '../endpoints';
import { AgentAuthError, PolicyDenied, TokenExchangeFailed } from '../errors';
import { HttpClient } from '../httpClient';
import { TokenStore } from '../store/base';
import { ApprovalRequest, Credential, Mode, VaultToken, vaultTokenExpired } from '../types';
import { ApprovalGate } from './base';

export interface GetResourceTokenArgs {
  resource: string;
  scopes?: string[];
  requireApproval?: ApprovalRequest;
  forceRefresh?: boolean;
  /** Mint a user-scoped Resource token using this user's Descope access token. */
  actAsUserToken?: string;
}

export interface ResourcesClientDeps {
  http: HttpClient;
  getCredential: () => Promise<Credential>;
  store: TokenStore;
  mode: Mode;
  approvalGate?: ApprovalGate;
  skewSeconds?: number;
}

const cacheKey = (resource: string, scopes?: string[]): string => {
  const scopePart = scopes && scopes.length ? [...scopes].sort().join(',') : '<defaults>';
  return `vault:resource:${resource}:${scopePart}`;
};

const errMsg = (body: any): string | undefined =>
  body?.error_description || body?.error || body?.errorDescription;

export class ResourcesClient {
  private readonly skew: number;

  constructor(private readonly deps: ResourcesClientDeps) {
    this.skew = deps.skewSeconds ?? 60;
  }

  async getToken(args: GetResourceTokenArgs): Promise<VaultToken> {
    if (this.deps.mode === 'execute') {
      throw new AgentAuthError(
        'raw token fetch is disabled in execute mode; the token stays vaulted.',
      );
    }

    if (args.requireApproval) {
      if (!this.deps.approvalGate) {
        throw new AgentAuthError(
          'requireApproval was set but no approval provider is configured on the client; ' +
            'pass approval: new CibaProvider(...) to AgentAuthClient',
        );
      }
      await this.deps.approvalGate(args.requireApproval);
    }

    const key = cacheKey(args.resource, args.scopes);
    if (!args.forceRefresh) {
      const cached = await this.cacheGet(key);
      if (cached) return cached;
    }

    // The subject is either an explicit user token (user-scoped) or the client's
    // own credential. A Management Key is not an OAuth token, so it cannot be the
    // subject of a token-exchange.
    let subjectToken: string;
    if (args.actAsUserToken) {
      subjectToken = args.actAsUserToken;
    } else {
      const cred = await this.deps.getCredential();
      if (cred.kind === 'management_key') {
        throw new AgentAuthError(
          'Resource tokens use the token-exchange grant and require an OAuth agent identity ' +
            '(Client ID/Secret via a phase-1 provider) or an actAsUserToken, not a Management Key.',
        );
      }
      subjectToken = cred.token;
    }

    const data: Record<string, string> = {
      grant_type: GRANT_TOKEN_EXCHANGE,
      subject_token: subjectToken,
      subject_token_type: TOKEN_TYPE_ACCESS_TOKEN,
      resource: args.resource,
    };
    if (args.scopes && args.scopes.length) data.scope = args.scopes.join(' ');

    const resp = await this.deps.http.postForm(OAUTH2_TOKEN, data);
    if (resp.statusCode === 401 || resp.statusCode === 403) {
      throw new PolicyDenied(
        `policy denied for resource '${args.resource}' ` +
          `(${resp.statusCode}): ${errMsg(resp.json) ?? resp.text}`,
        { connection: args.resource, scopes: args.scopes },
      );
    }
    if (!resp.ok || !resp.json?.access_token) {
      throw new TokenExchangeFailed(
        `resource token-exchange failed (${resp.statusCode}): ${errMsg(resp.json) ?? resp.text}`,
        { statusCode: resp.statusCode },
      );
    }

    const token = toVaultToken(resp.json, args.resource);
    await this.cacheSet(key, token);
    return token;
  }

  private async cacheGet(key: string): Promise<VaultToken | undefined> {
    const raw = await this.deps.store.get(key);
    if (!raw) return undefined;
    let token: VaultToken;
    try {
      token = JSON.parse(raw) as VaultToken;
    } catch {
      return undefined;
    }
    if (vaultTokenExpired(token, this.skew)) {
      await this.deps.store.delete(key);
      return undefined;
    }
    return token;
  }

  private async cacheSet(key: string, token: VaultToken): Promise<void> {
    const ttl =
      token.expiresAt !== undefined ? Math.max(0, token.expiresAt - Date.now() / 1000) : undefined;
    await this.deps.store.set(key, JSON.stringify(token), ttl);
  }
}

function toVaultToken(body: any, resource: string): VaultToken {
  const expiresAt =
    typeof body.expires_in === 'number' ? Date.now() / 1000 + body.expires_in : undefined;
  const { scope } = body;
  const scopes = typeof scope === 'string' && scope ? scope.split(' ') : [];
  const raw: Record<string, unknown> = {};
  Object.entries(body).forEach(([k, v]) => {
    if (k !== 'access_token') raw[k] = v;
  });
  return {
    accessToken: String(body.access_token),
    tokenType: body.token_type || 'Bearer',
    expiresAt,
    scopes,
    hasRefreshToken: false,
    appId: resource,
    raw,
  };
}
