/**
 * The phase-1 credential provider contract.
 *
 * A provider encodes one acquisition strategy. The client never cares which
 * provider it holds -- it just asks for a current credential and the provider
 * refreshes transparently underneath.
 *
 * Credentials are cached in memory and, when the provider exposes a stable storage
 * key, persisted to the pluggable `TokenStore` -- including the refresh token, kept
 * beyond the access token's expiry so a restarted/multi-process agent can refresh
 * instead of re-running an interactive flow (device code, authorization code, CIBA).
 */

import { GRANT_REFRESH_TOKEN, OAUTH2_TOKEN } from '../endpoints';
import { CredentialAcquisitionFailed } from '../errors';
import { HttpClient, HttpResponse } from '../httpClient';
import { TokenStore } from '../store/base';
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
  /** Privileged providers (management key) bypass Policies. */
  readonly kind: CredentialKind = 'agent_token';

  protected http?: HttpClient;

  protected projectId?: string;

  protected store?: TokenStore;

  private cached?: Credential;

  /** Wired by AgentAuthClient so the provider can talk to Descope and persist. */
  bind(http: HttpClient, projectId: string, store?: TokenStore): void {
    this.http = http;
    this.projectId = projectId;
    this.store = store;
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

    // Cold start: nothing in memory -> try the store (survives restarts).
    if (!this.cached) {
      const loaded = await this.load();
      if (loaded) {
        this.cached = loaded;
        if (!credentialExpired(loaded)) return loaded;
      }
    }

    if (this.cached?.refreshToken) {
      try {
        this.cached = await this.doRefresh(this.cached);
        await this.save(this.cached);
        return this.cached;
      } catch (err) {
        if (!(err instanceof CredentialAcquisitionFailed)) throw err;
        // fall through to a fresh acquisition
      }
    }

    this.cached = await this.acquire();
    await this.save(this.cached);
    return this.cached;
  }

  /** Force a refresh (or re-acquire if no refresh token is held). */
  async refresh(): Promise<Credential> {
    const base = this.cached ?? (await this.load());
    this.cached =
      base?.refreshToken !== undefined ? await this.doRefresh(base) : await this.acquire();
    await this.save(this.cached);
    return this.cached;
  }

  /** Run the provider's flow and return a fresh credential. */
  protected abstract acquire(): Promise<Credential>;

  /** A stable key to persist this credential under, or undefined to skip persistence. */
  protected storageKey(): string | undefined {
    return undefined;
  }

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

  // -- persistence --------------------------------------------------------

  private async save(cred: Credential): Promise<void> {
    const key = this.storageKey();
    if (!key || !this.store) return;
    // No TTL: the refresh token must outlive the access token's expiry.
    await this.store.set(key, JSON.stringify(cred));
  }

  private async load(): Promise<Credential | undefined> {
    const key = this.storageKey();
    if (!key || !this.store) return undefined;
    const raw = await this.store.get(key);
    if (!raw) return undefined;
    try {
      return JSON.parse(raw) as Credential;
    } catch {
      return undefined;
    }
  }
}

export type { HttpResponse };
