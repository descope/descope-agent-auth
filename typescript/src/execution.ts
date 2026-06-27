/**
 * The fetch-vs-execute seam (forward-compat for the hosted proxy).
 *
 * - `mode: 'fetch'` (default, ships today): phase 2 returns the raw downstream
 *   token to the caller's code. The token lives in the agent process.
 * - `mode: 'execute'` (future, lands with the proxy): phase 2 does NOT return the
 *   raw token. Instead the SDK routes the actual downstream API call through
 *   Descope's hosted execution endpoint, where the token stays vaulted, the call
 *   is policy-checked and audited, and only the result comes back.
 *
 * Both modes share one ergonomic. Only the fetch path is wired here; the execute
 * path is stubbed behind the `mode` flag so flipping to it later is a config
 * change, not a rewrite.
 */

import { AgentAuthError } from './errors';
import { Mode, VaultToken } from './types';
import { FetchArgs, VaultBackend } from './vault/base';

/**
 * Describes a downstream API call for execute mode. In execute mode the caller
 * passes one of these instead of receiving a token; Descope makes the call with
 * the vaulted token and returns only the result.
 */
export interface ToolRequest {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: unknown;
}

export class Execution {
  constructor(
    private readonly modeValue: Mode,
    private readonly backend: VaultBackend,
  ) {}

  get mode(): Mode {
    return this.modeValue;
  }

  /** Fetch path: return the raw vault token (fetch mode only). */
  async fetchToken(args: FetchArgs): Promise<VaultToken> {
    if (this.modeValue === 'execute') {
      throw new AgentAuthError(
        'raw token fetch is disabled in execute mode; the token stays vaulted. Use ' +
          'execute() to route the call through Descope instead.',
      );
    }
    return this.backend.fetch(args);
  }

  /**
   * Generate a connect URL. Available in both modes — authorizing a user is
   * independent of whether token fetch or hosted execution is used.
   */
  async getConnectUrl(
    connectBody: Record<string, unknown> | undefined,
    actAsUserToken?: string,
  ): Promise<string | undefined> {
    return this.backend.getConnectUrl(connectBody, actAsUserToken);
  }

  /**
   * Execute path: route the call through Descope's hosted execution endpoint.
   * Stubbed until that endpoint ships; the seam exists so enabling it is a `mode`
   * change for the developer, not a rewrite.
   */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async execute(_request: ToolRequest, _args: FetchArgs): Promise<unknown> {
    if (this.modeValue !== 'execute') {
      throw new AgentAuthError("execute() requires the client to be created with mode: 'execute'");
    }
    throw new Error(
      "mode: 'execute' routes calls through Descope's hosted execution endpoint, which is " +
        "not yet available in this SDK build. Use mode: 'fetch' for now.",
    );
  }
}
