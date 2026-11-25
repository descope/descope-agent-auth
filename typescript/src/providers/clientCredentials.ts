/**
 * ClientCredentialsProvider -- autonomous agent, no user in the loop.
 *
 * The simplest phase-1 path: exchange `clientId` + `clientSecret` for an access
 * token. A client secret is unavoidable here -- it is intrinsic to an agent
 * authenticating as itself.
 */

import { GRANT_CLIENT_CREDENTIALS, OAUTH2_APPS_TOKEN } from '../endpoints';
import { CredentialAcquisitionFailed } from '../errors';
import { base64 } from '../runtime';
import type { Credential } from '../types';
import { CredentialProvider, errMessage, tokenResponseToCredential } from './base';

export interface ClientCredentialsOptions {
  clientId: string;
  clientSecret: string;
  scopes?: string[];
}

export class ClientCredentialsProvider extends CredentialProvider {
  readonly kind = 'agent_token';

  // Agentic Clients are inbound apps: acquire and refresh on the inbound-apps server.
  protected readonly refreshEndpoint = OAUTH2_APPS_TOKEN;

  // The agent client itself: its own Resource tokens use client_credentials.
  readonly actsAsClient = true;

  private readonly clientId: string;

  private readonly clientSecret: string;

  private readonly scopes: string[];

  constructor(opts: ClientCredentialsOptions) {
    super();
    this.clientId = opts.clientId;
    this.clientSecret = opts.clientSecret;
    this.scopes = opts.scopes ?? [];
  }

  private basicAuth(): string {
    return `Basic ${base64(`${this.clientId}:${this.clientSecret}`)}`;
  }

  protected async acquire(): Promise<Credential> {
    const data: Record<string, string> = { grant_type: GRANT_CLIENT_CREDENTIALS };
    if (this.scopes.length) data.scope = this.scopes.join(' ');
    // Agentic Clients are inbound apps, served by the /v1/apps/<projectId>
    // authorization server, whose token endpoint is /oauth2/v1/apps/token.
    const resp = await this.requireHttp().postForm(OAUTH2_APPS_TOKEN, data, {
      Authorization: this.basicAuth(),
    });
    if (!resp.ok) {
      throw new CredentialAcquisitionFailed(
        `client_credentials acquisition failed (${resp.statusCode}): ` +
          `${errMessage(resp.json) ?? resp.text}`,
      );
    }
    return tokenResponseToCredential(resp.json, this.kind);
  }

  protected storageKey(): string {
    return `cred:client_credentials:${this.projectId}:${this.clientId}`;
  }

  clientAuth(): Record<string, string> {
    return { client_id: this.clientId, client_secret: this.clientSecret };
  }
}
