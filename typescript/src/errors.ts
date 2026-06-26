/**
 * Typed errors for the Descope Agent Auth SDK.
 *
 * The headline case -- "connection not yet authorized" -- is modeled as a
 * first-class signal carrying the connect URL, mirroring how Auth0 models
 * interrupts. Each error is specific enough that a coding agent generating an
 * integration can handle the re-auth and approval cases without guessing.
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
 */
export class ConnectionAuthorizationRequired extends AgentAuthError {
  connectUrl?: string;

  connection?: string;

  identifier?: string;

  constructor(
    message: string,
    opts: { connectUrl?: string; connection?: string; identifier?: string } = {},
  ) {
    super(message);
    this.connectUrl = opts.connectUrl;
    this.connection = opts.connection;
    this.identifier = opts.identifier;
  }
}

/** The agent token lacks Connection Policy permission for this connection/scope. */
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
