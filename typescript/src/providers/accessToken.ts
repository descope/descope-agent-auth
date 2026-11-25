/**
 * AccessTokenProvider -- bring your own Descope access token.
 *
 * Use when you *already hold* a Descope access token -- most commonly a **user's**
 * token obtained from your app's own login (its session, device-code, or CIBA) --
 * and want the agent to act with it for **user-scoped** downstream access. No
 * acquisition happens: the SDK wields the token you supply (and refreshes only if
 * you also provide a refresh token).
 *
 *     const client = new AgentAuthClient({
 *       projectId: 'P2...',
 *       credential: new AccessTokenProvider({ accessToken: userJwt }),
 *     });
 *     // user-scoped: the vault fetch runs as this user
 *     const gh = await client.connections.getToken({ connection: 'github', identifier: userId });
 *
 * This provider holds no client secret, so it cannot authenticate a token exchange:
 * `resources.getToken` throws `AgentAuthError` on such a client. For user-scoped
 * Resource tokens, and for a single shared client serving many users, build the
 * client with `ClientCredentialsProvider` and pass `actAsUserToken` per call on
 * `connections.getToken` / `resources.getToken`.
 */

import type { Credential } from '../types';
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
