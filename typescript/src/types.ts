/**
 * Shared types for the Descope Agent Auth SDK.
 *
 * Plain data shapes with no behavior so they can cross the public API surface
 * without leaking implementation details.
 */

/**
 * How a phase-1 credential is governed downstream. `agent_token` credentials are
 * subject to Connection Policies at exchange time; `management_key` credentials
 * bypass those policies entirely and grant broad vault access (never recommended).
 */
export type CredentialKind = 'agent_token' | 'management_key';

/**
 * The execution seam (see spec). `fetch` returns the raw downstream token to the
 * caller (ships today). `execute` is reserved for the future hosted-execution
 * endpoint where the token stays vaulted and only the call result returns.
 */
export type Mode = 'fetch' | 'execute';

export const isPrivileged = (kind: CredentialKind): boolean => kind === 'management_key';

/** A phase-1 Descope credential held by a provider. */
export interface Credential {
  /** Bearer value used to authenticate to Descope (access token or management key). */
  token: string;
  kind: CredentialKind;
  /** Unix seconds; `undefined` means it does not expire on its own (e.g. a key). */
  expiresAt?: number;
  refreshToken?: string;
}

export const credentialExpired = (cred: Credential, skewSeconds = 60): boolean => {
  if (cred.expiresAt === undefined) return false;
  return Date.now() / 1000 >= cred.expiresAt - skewSeconds;
};

/** A downstream token returned from the Descope vault (phase 2). */
export interface VaultToken {
  /** The provider token (GitHub, Slack, ...) or resource token the caller uses. */
  accessToken: string;
  tokenType: string;
  /** Unix seconds. */
  expiresAt?: number;
  scopes: string[];
  refreshToken?: string;
  hasRefreshToken: boolean;
  appId?: string;
  userId?: string;
  /** The raw token object minus secret fields, for introspection. */
  raw?: Record<string, unknown>;
}

export const vaultTokenExpired = (token: VaultToken, skewSeconds = 60): boolean => {
  if (token.expiresAt === undefined) return false;
  return Date.now() / 1000 >= token.expiresAt - skewSeconds;
};

/**
 * A user-action-required state surfaced by interactive phase-1 flows (device code
 * and CIBA): show the user what to do, then the SDK polls to completion.
 */
export interface PendingAuthorization {
  verificationUri?: string;
  verificationUriComplete?: string;
  userCode?: string;
  expiresAt?: number;
  intervalSeconds: number;
  message?: string;
}

/**
 * A just-in-time CIBA approval gate for a single sensitive exchange/action.
 * Distinct from acquisition: the agent already holds a working credential, but a
 * real person must sign off on a trusted device before this one step proceeds.
 */
export interface ApprovalRequest {
  loginHint: string;
  bindingMessage?: string;
  scopes?: string[];
  timeoutSeconds?: number;
}
