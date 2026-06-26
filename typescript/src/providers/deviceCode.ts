/**
 * DeviceCodeProvider -- headless agents (no browser).
 *
 * Starts the device authorization flow, surfaces a verification URL + user code
 * via a callback, then polls the token endpoint until the user completes the flow
 * on another device.
 *
 * Endpoint paths for the device-authorization request are UNVERIFIED -- see
 * `endpoints.DEVICE_AUTHORIZATION` and confirm against the project discovery doc.
 */

import { DEVICE_AUTHORIZATION, GRANT_DEVICE_CODE, OAUTH2_TOKEN } from '../endpoints';
import { CredentialAcquisitionFailed } from '../errors';
import { sleep } from '../httpClient';
import { Credential, PendingAuthorization } from '../types';
import { CredentialProvider, errMessage, tokenResponseToCredential } from './base';

export interface DeviceCodeOptions {
  clientId: string;
  scopes?: string[];
  /** Called once with the verification URL/code so the caller can display it. */
  onPending?: (pending: PendingAuthorization) => void;
  maxWaitSeconds?: number;
}

export class DeviceCodeProvider extends CredentialProvider {
  readonly kind = 'agent_token';

  private readonly clientId: string;

  private readonly scopes: string[];

  private readonly onPending?: (pending: PendingAuthorization) => void;

  private readonly maxWaitSeconds: number;

  constructor(opts: DeviceCodeOptions) {
    super();
    this.clientId = opts.clientId;
    this.scopes = opts.scopes ?? [];
    this.onPending = opts.onPending;
    this.maxWaitSeconds = opts.maxWaitSeconds ?? 300;
  }

  /** Returns `[deviceCode, pending]`; the deviceCode is kept local, never surfaced. */
  private async start(): Promise<[string, PendingAuthorization]> {
    const data: Record<string, string> = { client_id: this.clientId };
    if (this.scopes.length) data.scope = this.scopes.join(' ');
    const resp = await this.requireHttp().postForm(DEVICE_AUTHORIZATION, data);
    if (!resp.ok || !resp.json) {
      throw new CredentialAcquisitionFailed(
        `device authorization request failed (${resp.statusCode}): ` +
          `${errMessage(resp.json) ?? resp.text}`,
      );
    }
    const body = resp.json;
    if (!body.device_code) {
      throw new CredentialAcquisitionFailed('device authorization response missing device_code');
    }
    const pending: PendingAuthorization = {
      verificationUri: body.verification_uri,
      verificationUriComplete: body.verification_uri_complete,
      userCode: body.user_code,
      intervalSeconds: Number(body.interval ?? 5),
      expiresAt: body.expires_in ? Date.now() / 1000 + Number(body.expires_in) : undefined,
    };
    return [String(body.device_code), pending];
  }

  protected async acquire(): Promise<Credential> {
    const [deviceCode, pending] = await this.start();
    if (this.onPending) this.onPending(pending);

    let interval = pending.intervalSeconds;
    const hardDeadline = Date.now() / 1000 + this.maxWaitSeconds;
    const deadline = Math.min(pending.expiresAt ?? hardDeadline, hardDeadline);

    while (Date.now() / 1000 < deadline) {
      // eslint-disable-next-line no-await-in-loop
      await sleep(interval * 1000);
      // eslint-disable-next-line no-await-in-loop
      const resp = await this.requireHttp().postForm(OAUTH2_TOKEN, {
        grant_type: GRANT_DEVICE_CODE,
        device_code: deviceCode,
        client_id: this.clientId,
      });
      if (resp.ok) {
        return tokenResponseToCredential(resp.json, this.kind);
      }
      const error = resp.json?.error;
      if (error === 'authorization_pending') continue; // eslint-disable-line no-continue
      if (error === 'slow_down') {
        interval += 5;
        continue; // eslint-disable-line no-continue
      }
      throw new CredentialAcquisitionFailed(
        `device flow failed: ${errMessage(resp.json) ?? resp.text}`,
      );
    }
    throw new CredentialAcquisitionFailed('device flow timed out before user approval');
  }
}
