/**
 * ResourcesClient -- fetch a Descope **Resource** token.
 *
 * A Resource is an API you build and protect with Descope acting as the OAuth
 * authorization server. Unlike a Connection token (a stored API key / provider
 * OAuth token pulled from the vault), a Resource token is minted on the fly at the
 * inbound-apps token endpoint (`/oauth2/v1/apps/token`, per the
 * `/v1/apps/<projectId>` discovery document), always authenticated by a
 * confidential agent client (`client_id` + `client_secret`). Two grants apply:
 *
 * - **The agent acting as itself** (a `ClientCredentialsProvider` client, no
 *   `actAsUserToken`): a `client_credentials` request that names the `resource`.
 *   Descope's client-access Policies decide which scopes it gets.
 * - **The agent acting for a subject** (`actAsUserToken`, or a phase-1 credential
 *   that represents a user, such as CIBA): an RFC 8693 token exchange of that
 *   subject token. Descope's token-exchange Policies decide the scopes, and the
 *   authenticating client is recorded as `act.sub` so the downstream API can see
 *   which agent is acting for the user.
 *
 * A Management Key cannot mint Resource tokens.
 */

import {
  GRANT_CLIENT_CREDENTIALS,
  GRANT_TOKEN_EXCHANGE,
  OAUTH2_APPS_TOKEN,
  TOKEN_TYPE_ACCESS_TOKEN,
} from '../endpoints';
import { sha256Base64Url } from '../runtime';
import {
  AgentAuthError,
  CredentialAcquisitionFailed,
  PolicyDenied,
  TokenExchangeFailed,
} from '../errors';
import { HttpClient } from '../httpClient';
import { TokenStore } from '../store/base';
import { ApprovalRequest, Credential, Mode, VaultToken, vaultTokenExpired } from '../types';
import { ApprovalGate } from './base';

export interface GetResourceTokenArgs {
  resource: string;
  scopes?: string[];
  /** RFC 8693 audience claim, when the provider requires a specific audience. */
  audience?: string[];
  requireApproval?: ApprovalRequest;
  forceRefresh?: boolean;
  /** Mint a user-scoped Resource token using this user's Descope access token. */
  actAsUserToken?: string;
}

export interface ResourcesClientDeps {
  http: HttpClient;
  getCredential: () => Promise<Credential>;
  /** Confidential-client auth for the exchange (`client_id` + `client_secret`), if any. */
  getClientAuth: () => Record<string, string> | undefined;
  /**
   * True when the provider's identity is the agent client: its own Resource tokens
   * use the `client_credentials` grant rather than exchanging its credential.
   */
  actsAsClient?: boolean;
  /** The provider's stable identity, when it has one (CIBA: client + user). */
  getIdentityKey?: () => string | undefined;
  store: TokenStore;
  mode: Mode;
  approvalGate?: ApprovalGate;
  skewSeconds?: number;
  /** When false, never read/write the token cache so Policies are re-enforced each call. */
  cacheTokens?: boolean;
}

const cacheKey = (
  resource: string,
  scopes: string[] | undefined,
  audience: string[] | undefined,
  clientId: string,
  subject: string,
): string => {
  const scopePart = scopes && scopes.length ? [...scopes].sort().join(',') : '<defaults>';
  const audPart = audience && audience.length ? [...audience].sort().join(',') : '<none>';
  // A Resource token belongs to one (actor, subject) pair: the client that
  // authenticates the request (act.sub on an exchange) and the subject. Key by
  // both so a shared TokenStore never serves one client's or one user's token to
  // another. `subject` is 'self' (client_credentials), a digest of the token being
  // exchanged, or 'id:' + a digest of the provider's stable identity (see
  // CredentialProvider.identityKey). No raw token or identity lands in the key.
  return `vault:resource:${clientId}:${subject}:${resource}:${audPart}:${scopePart}`;
};

const errMsg = (body: any): string | undefined =>
  body?.error_description || body?.errorMessage || body?.error || body?.errorDescription;

// OAuth error codes (RFC 6749 / 8693 / 8707) that mean "no Policy grants this".
const POLICY_ERRORS = new Set(['unauthorized_client', 'invalid_target', 'access_denied']);
// Descope's own codes for the same, sent in the legacy envelope (`errorCode`):
// E063309 for the agent's own token, E063313 when acting for a user.
const POLICY_ERROR_CODES = new Set(['E063309', 'E063313']);
const SCOPE_NOT_GRANTED = 'requested scope not granted';

/**
 * Classify a failed Resource token response by the error the server returns:
 * `client` (the agent's client auth was rejected), `policy` (no Policy grants the
 * request), or `other`. Every request carries the client secret, so a 401 is
 * usually a bad secret, not a Policy decision: go by the OAuth `error` rather than
 * the HTTP status. Descope can also send its legacy envelope (strict OAuth errors
 * off), where `errorDescription` carries the OAuth code and `errorCode` /
 * `errorMessage` Descope's own code and reason.
 */
export const tokenErrorClass = (statusCode: number, body: any): 'client' | 'policy' | 'other' => {
  const b = body && typeof body === 'object' ? body : {};
  const codes = [b.error, b.errorDescription];
  if (codes.includes('invalid_client')) return 'client';
  if (codes.some((c) => POLICY_ERRORS.has(c)) || POLICY_ERROR_CODES.has(b.errorCode)) {
    return 'policy';
  }
  const reason = [b.error_description, b.errorMessage].filter(Boolean).join(' ').toLowerCase();
  if (reason.includes(SCOPE_NOT_GRANTED) || statusCode === 403) return 'policy';
  return 'other';
};

export class ResourcesClient {
  private readonly skew: number;

  private readonly cacheTokens: boolean;

  constructor(private readonly deps: ResourcesClientDeps) {
    this.skew = deps.skewSeconds ?? 60;
    this.cacheTokens = deps.cacheTokens ?? true;
  }

  async getToken(args: GetResourceTokenArgs): Promise<VaultToken> {
    if (this.deps.mode === 'execute') {
      throw new AgentAuthError(
        'raw token fetch is disabled in execute mode; the token stays vaulted.',
      );
    }

    // Descope rejects unauthenticated token-exchange requests, and the
    // authenticating client is what lands in act.sub. Fail before any network call
    // (or approval prompt) when the provider has no client secret to offer.
    const clientAuth = this.deps.getClientAuth();
    if (!clientAuth) {
      throw new AgentAuthError(
        'Resource tokens use the token-exchange grant, which Descope only serves to an ' +
          'authenticated agent client. Configure the client with new ClientCredentialsProvider(' +
          '{ clientId, clientSecret }) and pass actAsUserToken to act for a user.',
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

    // The subject is an explicit user token (user-scoped), nothing (a
    // client-credentials agent acting as itself), or the client's own phase-1
    // credential. The cache key is bound to the subject. For the own-credential
    // path, a provider with a stable identity (CIBA: one user) is keyed by that
    // identity, so a cached Resource token is served without touching -- and
    // possibly refreshing or re-approving -- the phase-1 credential, and the entry
    // survives that credential's rotation. Without one, the credential must be
    // resolved first so its digest can key the entry.
    const asSelf = !args.actAsUserToken && !!this.deps.actsAsClient;
    let subjectToken: string | undefined = args.actAsUserToken || undefined;
    let subject: string;
    if (subjectToken !== undefined) {
      subject = await sha256Base64Url(subjectToken);
    } else if (asSelf) {
      subject = 'self';
    } else {
      const identity = this.deps.getIdentityKey?.();
      if (identity) {
        subject = `id:${await sha256Base64Url(identity)}`;
      } else {
        subjectToken = await this.ownSubjectToken();
        subject = await sha256Base64Url(subjectToken);
      }
    }

    const key = cacheKey(
      args.resource,
      args.scopes,
      args.audience,
      clientAuth.client_id ?? '',
      subject,
    );
    if (this.cacheTokens && !args.forceRefresh) {
      const cached = await this.cacheGet(key);
      if (cached) return cached;
    }
    if (!asSelf && subjectToken === undefined) subjectToken = await this.ownSubjectToken();

    const data: Record<string, string | string[]> =
      asSelf || subjectToken === undefined
        ? // The agent acting as itself: Descope applies client-access Policies only
          // to a client_credentials request that names the resource.
          {
            grant_type: GRANT_CLIENT_CREDENTIALS,
            resource: args.resource,
            ...clientAuth,
          }
        : {
            grant_type: GRANT_TOKEN_EXCHANGE,
            subject_token: subjectToken,
            subject_token_type: TOKEN_TYPE_ACCESS_TOKEN,
            resource: args.resource,
            ...clientAuth,
          };
    if (args.scopes && args.scopes.length) data.scope = args.scopes.join(' ');
    if (args.audience && args.audience.length) data.audience = args.audience;

    const resp = await this.deps.http.postForm(OAUTH2_APPS_TOKEN, data);
    if (!resp.ok) {
      const reason = errMsg(resp.json) ?? resp.text;
      const errorClass = tokenErrorClass(resp.statusCode, resp.json);
      if (errorClass === 'client') {
        throw new CredentialAcquisitionFailed(
          `Descope rejected the agent client (${resp.statusCode}): ${reason}. ` +
            'Check the clientId and clientSecret.',
        );
      }
      if (errorClass === 'policy') {
        throw new PolicyDenied(
          `policy denied for resource '${args.resource}' (${resp.statusCode}): ${reason}`,
          { connection: args.resource, scopes: args.scopes },
        );
      }
    }
    if (!resp.ok || !resp.json?.access_token) {
      throw new TokenExchangeFailed(
        `resource token request failed (${resp.statusCode}): ${errMsg(resp.json) ?? resp.text}`,
        { statusCode: resp.statusCode },
      );
    }

    const token = toVaultToken(resp.json, args.resource);
    if (this.cacheTokens) await this.cacheSet(key, token);
    return token;
  }

  /** The client's own phase-1 credential as the exchange subject. */
  private async ownSubjectToken(): Promise<string> {
    const cred = await this.deps.getCredential();
    // A Management Key is not an OAuth token, so it cannot be the subject of a
    // token exchange.
    if (cred.kind === 'management_key') {
      throw new AgentAuthError(
        'Resource tokens use the token-exchange grant and require an OAuth agent identity ' +
          '(Client ID/Secret via a phase-1 provider) or an actAsUserToken, not a Management Key.',
      );
    }
    return cred.token;
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
