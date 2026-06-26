/**
 * The phase-1 credential provider contract.
 *
 * A provider encodes one acquisition strategy. The client never cares which
 * provider it holds -- it just asks for a current credential and the provider
 * refreshes transparently underneath. This base handles caching + lazy refresh,
 * so every provider gets consistent refresh-on-get behavior for free.
 */

import { GRANT_REFRESH_TOKEN, OAUTH2_TOKEN } from '../endpoints';
import { CredentialAcquisitionFailed } from '../errors';
import { HttpClient, HttpResponse } from '../httpClient';
import { Credential, CredentialKind, credentialExpired, isPrivileged } from '../types';

export const errMessage = (body: any): string | undefined => {
  if (!body) return undefined;
  return body.error_description || body.error || body.errorDescription;
};

/** Parse a standard OAuth2 token response into a `Credential`. */
export const tokenResponseToCredential = (
  body: any,
  kind: CredentialKind,
  fallback?: Credential,
): Credential => {
  if (!body || !body.access_token) {
    throw new CredentialAcquisitionFailed('token response missing access_token');
  }
  let expiresAt: number | undefined;
  if (typeof body.expires_in === 'number') {
    expiresAt = Date.now() / 1000 + body.expires_in;
  }
  const refreshToken = body.refresh_token ?? fallback?.refreshToken;
  return { token: String(body.access_token), kind, expiresAt, refreshToken };
};

export abstract class CredentialProvider {
  /** Privileged providers (management key) bypass Connection Policies. */
  readonly kind: CredentialKind = 'agent_token';

  protected http?: HttpClient;

  protected projectId?: string;

  private cached?: Credential;

  /** Wired by AgentAuthClient so the provider can talk to Descope. */
  bind(http: HttpClient, projectId: string): void {
    this.http = http;
    this.projectId = projectId;
  }

  protected requireHttp(): HttpClient {
    if (!this.http) {
      throw new CredentialAcquisitionFailed(
        'provider is not bound to a client; construct it via AgentAuthClient',
      );
    }
    return this.http;
  }

  get isPrivileged(): boolean {
    return isPrivileged(this.kind);
  }

  /** Return a current, valid credential, refreshing/acquiring as needed. */
  async getCredential(): Promise<Credential> {
    if (this.cached && !credentialExpired(this.cached)) {
      return this.cached;
    }
    if (this.cached?.refreshToken) {
      try {
        this.cached = await this.doRefresh(this.cached);
        return this.cached;
      } catch (err) {
        if (!(err instanceof CredentialAcquisitionFailed)) throw err;
        // fall through to a fresh acquisition
      }
    }
    this.cached = await this.acquire();
    return this.cached;
  }

  /** Force a refresh (or re-acquire if no refresh token is held). */
  async refresh(): Promise<Credential> {
    this.cached =
      this.cached?.refreshToken !== undefined
        ? await this.doRefresh(this.cached)
        : await this.acquire();
    return this.cached;
  }

  /** Run the provider's flow and return a fresh credential. */
  protected abstract acquire(): Promise<Credential>;

  /** Default refresh via the OAuth2 `refresh_token` grant. Override as needed. */
  protected async doRefresh(current: Credential): Promise<Credential> {
    if (!current.refreshToken) return this.acquire();
    const data: Record<string, string> = {
      grant_type: GRANT_REFRESH_TOKEN,
      refresh_token: current.refreshToken,
      ...this.refreshClientAuth(),
    };
    const resp = await this.requireHttp().postForm(OAUTH2_TOKEN, data);
    if (!resp.ok) {
      throw new CredentialAcquisitionFailed(
        `refresh failed (${resp.statusCode}): ${errMessage(resp.json) ?? resp.text}`,
      );
    }
    return tokenResponseToCredential(resp.json, this.kind, current);
  }

  /** Extra form fields / client auth for refresh. Override as needed. */
  protected refreshClientAuth(): Record<string, string> {
    return {};
  }
}

export type { HttpResponse };
