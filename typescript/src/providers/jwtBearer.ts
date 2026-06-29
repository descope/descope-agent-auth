/**
 * JwtBearerProvider -- exchange a signed external JWT for a Descope credential.
 *
 * RFC 7523 (`urn:ietf:params:oauth:grant-type:jwt-bearer`): present a JWT issued by a
 * trusted issuer you registered in Descope (e.g. a cloud provider's workload-identity
 * OIDC token, or another IdP) and Descope validates it against that issuer's JWKs and
 * issues its own token. Use when the agent already holds a signed assertion of its
 * identity rather than a client secret or a Descope access token.
 *
 * Requires the Descope client to have the JWT Bearer grant enabled and the issuer
 * registered as trusted. `assertion` may be a string or a (sync/async) function
 * returning a fresh JWT (useful for rotating workload tokens).
 */

import { GRANT_JWT_BEARER, OAUTH2_TOKEN } from '../endpoints';
import { CredentialAcquisitionFailed } from '../errors';
import { Credential } from '../types';
import { CredentialProvider, errMessage, tokenResponseToCredential } from './base';

export interface JwtBearerOptions {
  clientId: string;
  /** The signed external JWT, or a function returning a fresh one. */
  assertion: string | (() => string | Promise<string>);
  scopes?: string[];
}

export class JwtBearerProvider extends CredentialProvider {
  readonly kind = 'agent_token';

  private readonly clientId: string;

  private readonly assertion: string | (() => string | Promise<string>);

  private readonly scopes: string[];

  constructor(opts: JwtBearerOptions) {
    super();
    this.clientId = opts.clientId;
    this.assertion = opts.assertion;
    this.scopes = opts.scopes ?? [];
  }

  private async resolveAssertion(): Promise<string> {
    // A function lets the caller hand over a fresh JWT each acquisition (the
    // external assertion is itself short-lived).
    return typeof this.assertion === 'function' ? this.assertion() : this.assertion;
  }

  protected async acquire(): Promise<Credential> {
    const data: Record<string, string> = {
      grant_type: GRANT_JWT_BEARER,
      client_id: this.clientId,
      assertion: await this.resolveAssertion(),
    };
    if (this.scopes.length) data.scope = this.scopes.join(' ');
    const resp = await this.requireHttp().postForm(OAUTH2_TOKEN, data);
    if (!resp.ok) {
      throw new CredentialAcquisitionFailed(
        `jwt-bearer exchange failed (${resp.statusCode}): ${errMessage(resp.json) ?? resp.text}`,
      );
    }
    return tokenResponseToCredential(resp.json, this.kind);
  }

  protected storageKey(): string {
    return `cred:jwt_bearer:${this.projectId}:${this.clientId}`;
  }
}
