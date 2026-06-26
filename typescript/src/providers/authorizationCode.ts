/**
 * AuthorizationCodeProvider -- agents with a browser available.
 *
 * Standard redirect-based auth-code flow with PKCE. The SDK builds the authorize
 * URL and exchanges the returned code; the caller owns the redirect plumbing.
 * Either build the authorize URL, send the user, capture the code, then call
 * `complete(code)`, or construct with an `authorizationCode` for one-shot exchange.
 */

import { GRANT_AUTHORIZATION_CODE, OAUTH2_AUTHORIZE, OAUTH2_TOKEN } from '../endpoints';
import { CredentialAcquisitionFailed } from '../errors';
import { randomUrlToken, sha256UrlChallenge } from '../runtime';
import { Credential } from '../types';
import { CredentialProvider, errMessage, tokenResponseToCredential } from './base';

export interface AuthorizationCodeOptions {
  clientId: string;
  redirectUri: string;
  scopes?: string[];
  clientSecret?: string;
  authorizationCode?: string;
  codeVerifier?: string;
  /** Absolute base for `buildAuthorizeUrl`; defaults to a relative path. */
  baseUrlForAuthorize?: string;
}

export class AuthorizationCodeProvider extends CredentialProvider {
  readonly kind = 'agent_token';

  private readonly clientId: string;

  private readonly redirectUri: string;

  private readonly scopes: string[];

  private readonly clientSecret?: string;

  private code?: string;

  private verifier?: string;

  private readonly baseForAuthorize?: string;

  constructor(opts: AuthorizationCodeOptions) {
    super();
    this.clientId = opts.clientId;
    this.redirectUri = opts.redirectUri;
    this.scopes = opts.scopes ?? ['openid'];
    this.clientSecret = opts.clientSecret;
    this.code = opts.authorizationCode;
    this.verifier = opts.codeVerifier;
    this.baseForAuthorize = opts.baseUrlForAuthorize;
  }

  /** Build the authorize URL (with PKCE) for the caller to redirect to. */
  async buildAuthorizeUrl(state?: string): Promise<string> {
    const verifier = await randomUrlToken(32);
    const challenge = await sha256UrlChallenge(verifier);
    this.verifier = verifier;
    const params = new URLSearchParams({
      client_id: this.clientId,
      redirect_uri: this.redirectUri,
      response_type: 'code',
      scope: this.scopes.join(' '),
      code_challenge: challenge,
      code_challenge_method: 'S256',
    });
    if (state) params.set('state', state);
    const base = (this.baseForAuthorize ?? '').replace(/\/$/, '');
    return `${base}${OAUTH2_AUTHORIZE}?${params.toString()}`;
  }

  /** Supply the code captured at the redirect and acquire the credential. */
  async complete(authorizationCode: string): Promise<Credential> {
    this.code = authorizationCode;
    return this.refresh();
  }

  protected async acquire(): Promise<Credential> {
    if (!this.code) {
      throw new CredentialAcquisitionFailed(
        'no authorizationCode available; call buildAuthorizeUrl(), redirect the user, ' +
          'then complete(code)',
      );
    }
    const data: Record<string, string> = {
      grant_type: GRANT_AUTHORIZATION_CODE,
      code: this.code,
      redirect_uri: this.redirectUri,
      client_id: this.clientId,
    };
    if (this.verifier) data.code_verifier = this.verifier;
    if (this.clientSecret) data.client_secret = this.clientSecret;
    const resp = await this.requireHttp().postForm(OAUTH2_TOKEN, data);
    if (!resp.ok) {
      throw new CredentialAcquisitionFailed(
        `authorization_code exchange failed (${resp.statusCode}): ` +
          `${errMessage(resp.json) ?? resp.text}`,
      );
    }
    // An auth code is single-use; clear it so a later refresh uses refresh_token.
    this.code = undefined;
    return tokenResponseToCredential(resp.json, this.kind);
  }

  protected storageKey(): string {
    return `cred:authz:${this.projectId}:${this.clientId}`;
  }

  protected refreshClientAuth(): Record<string, string> {
    const out: Record<string, string> = { client_id: this.clientId };
    if (this.clientSecret) out.client_secret = this.clientSecret;
    return out;
  }
}
