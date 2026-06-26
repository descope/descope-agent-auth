/**
 * CibaProvider -- out-of-band user approval (Client-Initiated Backchannel Auth).
 *
 * CIBA does double duty:
 *   - As a phase-1 path, it acquires a user-bound token without the user being
 *     interactively present.
 *   - As a phase-2 gate, `authenticate()` requires a fresh approval before a
 *     single sensitive exchange/action (the gate wiring itself lands later).
 *
 * Endpoint paths and the CIBA grant-type string are UNVERIFIED -- see
 * `endpoints.CIBA_AUTHENTICATE` / `GRANT_CIBA` and confirm via discovery.
 */

import { CIBA_AUTHENTICATE, GRANT_CIBA, OAUTH2_TOKEN } from '../endpoints';
import { ApprovalDenied, ApprovalTimeout, CredentialAcquisitionFailed } from '../errors';
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
}

export class CibaProvider extends CredentialProvider {
  readonly kind = 'agent_token';

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
      const resp = await this.requireHttp().postForm(OAUTH2_TOKEN, this.pollBody(authReqId));
      if (resp.ok) {
        return tokenResponseToCredential(resp.json, this.kind);
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
    const resp = await this.requireHttp().postForm(CIBA_AUTHENTICATE, data);
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
}
