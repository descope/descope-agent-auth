/**
 * Typed errors for the Descope Agent Auth SDK.
 *
 * The headline case -- "connection not yet authorized" -- is modeled as a
 * first-class signal carrying the connect URL the caller redirects the user to.
 * Each error is specific enough that a coding agent generating an integration can
 * handle the re-auth and approval cases without guessing.
 */

export class AgentAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * The user has not yet connected (or has revoked) the downstream account. Catch
 * this and redirect the user to `connectUrl` to complete OAuth consent, then retry.
 * If Descope could not produce a connect URL, `connectUrl` is undefined and
 * `connectError` says why (for example a redirect URL the project does not allow).
 */
export class ConnectionAuthorizationRequired extends AgentAuthError {
  connectUrl?: string;

  connection?: string;

  identifier?: string;

  connectError?: string;

  constructor(
    message: string,
    opts: {
      connectUrl?: string;
      connection?: string;
      identifier?: string;
      connectError?: string;
    } = {},
  ) {
    super(message);
    this.connectUrl = opts.connectUrl;
    this.connection = opts.connection;
    this.identifier = opts.identifier;
    this.connectError = opts.connectError;
  }
}

/** Descope did not return a connect URL. The message carries Descope's reason. */
export class ConnectUrlFailed extends AgentAuthError {
  statusCode?: number;

  constructor(message: string, opts: { statusCode?: number } = {}) {
    super(message);
    this.statusCode = opts.statusCode;
  }
}

/** The agent token lacks Policy permission for this connection/scope. */
export class PolicyDenied extends AgentAuthError {
  connection?: string;

  scopes?: string[];

  constructor(message: string, opts: { connection?: string; scopes?: string[] } = {}) {
    super(message);
    this.connection = opts.connection;
    this.scopes = opts.scopes;
  }
}

/** Phase 1 failed: bad client credentials, device-flow timeout, etc. */
export class CredentialAcquisitionFailed extends AgentAuthError {}

/**
 * Descope rejected or did not apply a CIBA request's `authorizationDetails`.
 * Rejections come before any approval is sent: the type is not registered on the
 * requested resource, more than one element, over 4096 bytes, or nested deeper than 5.
 * Not retryable as is; fix the request. `errorDescription` is the server's reason.
 */
export class InvalidAuthorizationDetails extends CredentialAcquisitionFailed {
  readonly errorDescription: string;

  constructor(errorDescription: string) {
    super(errorDescription);
    this.errorDescription = errorDescription;
  }
}

/** Phase 2 transport or validation failure not covered by a more specific error. */
export class TokenExchangeFailed extends AgentAuthError {
  statusCode?: number;

  constructor(message: string, opts: { statusCode?: number } = {}) {
    super(message);
    this.statusCode = opts.statusCode;
  }
}

/** The CIBA gate: the user explicitly rejected the request. */
export class ApprovalDenied extends AgentAuthError {}

/** The CIBA gate: the user did not respond before the request expired. */
export class ApprovalTimeout extends AgentAuthError {}
