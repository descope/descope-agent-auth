/**
 * CibaProvider -- out-of-band user approval (Client-Initiated Backchannel Auth).
 *
 * CIBA does double duty:
 *   - As a phase-1 path, it acquires a user-bound token without the user being
 *     interactively present.
 *   - As a phase-2 gate, `authenticate()` requires a fresh approval before a
 *     single sensitive exchange/action (the gate wiring itself lands later).
 *
 * Descope serves CIBA only on the inbound-apps authorization server, so initiation,
 * polling and refresh go to `/oauth2/v1/apps/*`. `clientId` must be the Descope-issued inbound
 * app client ID: that route recovers the project from it.
 */

import { CIBA_AUTHENTICATE, GRANT_CIBA, OAUTH2_APPS_TOKEN } from '../endpoints';
import {
  ApprovalDenied,
  ApprovalTimeout,
  CredentialAcquisitionFailed,
  InvalidAuthorizationDetails,
} from '../errors';
import { sleep } from '../httpClient';
import { Credential } from '../types';
import { CredentialProvider, errMessage, tokenResponseToCredential } from './base';

export interface CibaOptions {
  clientId: string;
  loginHint: string;
  clientSecret?: string;
  bindingMessage?: string;
  scopes?: string[];
  maxWaitSeconds?: number;
}

export interface CibaAuthenticateArgs {
  loginHint: string;
  bindingMessage?: string;
  scopes?: string[];
  timeoutSeconds?: number;
  /** RFC 8707 resource indicator; one per CIBA request. */
  resource?: string;
  /** RFC 9396 details the user approves (e.g. a payment); types must be registered on `resource`. */
  authorizationDetails?: Record<string, unknown>[];
}

const requireAppliedDetails = (credential: Credential): void => {
  // A project with OAUTH_RAR off accepts the request but drops the details, so the
  // user approved only the binding message; never hand that back as a RAR approval.
  if (!credential.authorizationDetails?.length) {
    throw new InvalidAuthorizationDetails(
      'Descope did not apply authorization_details to the approval; ' +
        'check that RAR is enabled for the project',
    );
  }
};

export class CibaProvider extends CredentialProvider {
  readonly kind = 'agent_token';

  protected readonly refreshEndpoint = OAUTH2_APPS_TOKEN;

  private readonly clientId: string;

  private readonly clientSecret?: string;

  private readonly loginHint: string;

  private readonly bindingMessage?: string;

  private readonly scopes: string[];

  private readonly maxWaitSeconds: number;

  constructor(opts: CibaOptions) {
    super();
    this.clientId = opts.clientId;
    this.clientSecret = opts.clientSecret;
    this.loginHint = opts.loginHint;
    this.bindingMessage = opts.bindingMessage;
    this.scopes = opts.scopes ?? ['openid'];
    this.maxWaitSeconds = opts.maxWaitSeconds ?? 120;
  }

  protected async acquire(): Promise<Credential> {
    return this.authenticate({
      loginHint: this.loginHint,
      bindingMessage: this.bindingMessage,
      scopes: this.scopes,
      timeoutSeconds: this.maxWaitSeconds,
    });
  }

  /**
   * Run one full CIBA cycle (initiate + poll) and return the user-bound token.
   * Reused as both acquisition and the phase-2 approval gate. Throws
   * `ApprovalDenied` / `ApprovalTimeout` on rejection or expiry.
   *
   * With `authorizationDetails` the returned credential carries the approved details and
   * is never cached or stored, so every call asks the user again. Its refresh token, if
   * any, stays a handle to that same grant (RFC 9396 section 6); single use is the
   * resource server's to enforce. Throws `InvalidAuthorizationDetails` when Descope
   * rejects the details or does not apply them.
   */
  async authenticate(args: CibaAuthenticateArgs): Promise<Credential> {
    const { authReqId, expiresAt, interval: startInterval } = await this.initiate(args);
    let interval = startInterval;
    const timeout = args.timeoutSeconds ?? this.maxWaitSeconds;
    const deadline = Math.min(expiresAt, Date.now() / 1000 + timeout);

    while (Date.now() / 1000 < deadline) {
      // eslint-disable-next-line no-await-in-loop
      await sleep(interval * 1000);
      // eslint-disable-next-line no-await-in-loop
      const resp = await this.requireHttp().postForm(OAUTH2_APPS_TOKEN, this.pollBody(authReqId));
      if (resp.ok) {
        const credential = tokenResponseToCredential(resp.json, this.kind);
        if (args.authorizationDetails?.length) requireAppliedDetails(credential);
        return credential;
      }
      const error = resp.json?.error;
      if (error === 'authorization_pending') continue; // eslint-disable-line no-continue
      if (error === 'slow_down') {
        interval += 5;
        continue; // eslint-disable-line no-continue
      }
      if (error === 'access_denied' || error === 'denied') {
        throw new ApprovalDenied('user rejected the CIBA approval request');
      }
      if (error === 'expired_token') {
        throw new ApprovalTimeout('CIBA request expired before approval');
      }
      throw new CredentialAcquisitionFailed(
        `CIBA flow failed: ${errMessage(resp.json) ?? resp.text}`,
      );
    }
    throw new ApprovalTimeout('CIBA request timed out before user approval');
  }

  private async initiate(
    args: CibaAuthenticateArgs,
  ): Promise<{ authReqId: string; expiresAt: number; interval: number }> {
    const data: Record<string, string> = {
      client_id: this.clientId,
      login_hint: args.loginHint,
      scope: (args.scopes ?? this.scopes).join(' '),
    };
    if (this.clientSecret) data.client_secret = this.clientSecret;
    if (args.bindingMessage) data.binding_message = args.bindingMessage;
    if (args.resource) data.resource = args.resource;
    if (args.authorizationDetails?.length) {
      data.authorization_details = JSON.stringify(args.authorizationDetails);
    }
    const resp = await this.requireHttp().postForm(CIBA_AUTHENTICATE, data);
    if (!resp.ok && resp.json?.error === 'invalid_authorization_details') {
      throw new InvalidAuthorizationDetails(errMessage(resp.json) ?? resp.text);
    }
    if (!resp.ok || !resp.json) {
      throw new CredentialAcquisitionFailed(
        `CIBA initiation failed (${resp.statusCode}): ${errMessage(resp.json) ?? resp.text}`,
      );
    }
    const authReqId = resp.json.auth_req_id;
    if (!authReqId) {
      throw new CredentialAcquisitionFailed('CIBA initiation response missing auth_req_id');
    }
    const interval = Number(resp.json.interval ?? 5);
    const expiresIn = Number(resp.json.expires_in ?? this.maxWaitSeconds);
    return { authReqId, expiresAt: Date.now() / 1000 + expiresIn, interval };
  }

  private pollBody(authReqId: string): Record<string, string> {
    const body: Record<string, string> = {
      grant_type: GRANT_CIBA,
      auth_req_id: authReqId,
      client_id: this.clientId,
    };
    if (this.clientSecret) body.client_secret = this.clientSecret;
    return body;
  }

  protected storageKey(): string {
    // Keyed by the user (loginHint): the acquired token is user-bound.
    return `cred:ciba:${this.projectId}:${this.clientId}:${this.loginHint}`;
  }

  protected refreshClientAuth(): Record<string, string> {
    const out: Record<string, string> = { client_id: this.clientId };
    if (this.clientSecret) out.client_secret = this.clientSecret;
    return out;
  }
}
