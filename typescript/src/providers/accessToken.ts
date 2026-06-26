/**
 * AccessTokenProvider -- bring your own Descope access token.
 *
 * Use when you *already hold* a Descope access token -- most commonly a **user's**
 * token obtained from your app's authorization-code, device-code, or CIBA login --
 * and want the agent to act with it for **user-scoped** downstream access. No
 * acquisition happens: the SDK wields the token you supply (and refreshes only if
 * you also provide a refresh token).
 *
 *     const client = new AgentAuthClient({
 *       projectId: 'P2...',
 *       credential: new AccessTokenProvider({ accessToken: userJwt }),
 *     });
 *     // user-scoped: vault fetch + token-exchange both run as this user
 *     const gh = await client.connections.getToken({ connection: 'github', identifier: userId });
 *
 * For a single shared (autonomous) client serving many users, prefer the per-call
 * `actAsUserToken` override on `connections.getToken` / `resources.getToken`.
 */

import { Credential } from '../types';
import { CredentialProvider } from './base';

export interface AccessTokenOptions {
  accessToken: string;
  expiresAt?: number;
  refreshToken?: string;
}

export class AccessTokenProvider extends CredentialProvider {
  readonly kind = 'agent_token';

  private readonly accessToken: string;

  private readonly expiresAt?: number;

  private readonly refreshTokenValue?: string;

  constructor(opts: AccessTokenOptions) {
    super();
    this.accessToken = opts.accessToken;
    this.expiresAt = opts.expiresAt;
    this.refreshTokenValue = opts.refreshToken;
  }

  protected async acquire(): Promise<Credential> {
    // The token is supplied, not acquired; just hand it back.
    return {
      token: this.accessToken,
      kind: this.kind,
      expiresAt: this.expiresAt,
      refreshToken: this.refreshTokenValue,
    };
  }
}
