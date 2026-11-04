/**
 * Centralized Descope endpoint paths and grant-type constants.
 *
 * Every wire path the SDK touches lives here so it can be confirmed against the
 * Descope API reference in one place. Paths are relative to the configured
 * `baseUrl` (default `https://api.descope.com`).
 *
 * Constants marked UNVERIFIED still need confirming against the project's OIDC
 * discovery document (`/<projectId>/.well-known/openid-configuration`) before
 * relying on them:
 *   - DEVICE_AUTHORIZATION path
 *   - RESOURCE token endpoint shape
 */

// --- Phase 1: OAuth2 / OIDC (acquisition) -----------------------------------

/** client_credentials, refresh_token, device_code. */
export const OAUTH2_TOKEN = '/oauth2/v1/token';

/**
 * Token endpoint for an agent that authenticates as an inbound app client. CIBA polls
 * here (or the /apps/{projectId}/token variant) because OAUTH2_TOKEN does not serve
 * that grant.
 */
export const OAUTH2_APPS_TOKEN = '/oauth2/v1/apps/token';

/** UNVERIFIED -- confirm via discovery (device_authorization_endpoint). */
export const DEVICE_AUTHORIZATION = '/oauth2/v1/device';

/** CIBA is served only by the inbound-apps authorization server. */
export const CIBA_AUTHENTICATE = '/oauth2/v1/apps/bc-authorize';

/** OIDC discovery document (project-scoped). */
export const discovery = (projectId: string): string =>
  `/${projectId}/.well-known/openid-configuration`;

// --- Phase 2: vault exchange -------------------------------------------------

/** Fetch the latest stored outbound-app user token (Connection defaults). */
export const OUTBOUND_USER_TOKEN_LATEST = '/v1/mgmt/outbound/app/user/token/latest';

/** Fetch a stored outbound-app user token for an explicit scope set. */
export const OUTBOUND_USER_TOKEN = '/v1/mgmt/outbound/app/user/token';

/**
 * Tenant-scoped Connection tokens (a tenant-level API key / org-shared
 * OAuth token), distinct from Resource tokens (which use the token-exchange grant
 * below). Exposed via ConnectionsClient.getTenantToken.
 */
export const OUTBOUND_TENANT_TOKEN_LATEST = '/v1/mgmt/outbound/app/tenant/token/latest';
export const OUTBOUND_TENANT_TOKEN = '/v1/mgmt/outbound/app/tenant/token';

/** Request a connect URL the user visits to authorize a connection. */
export const OUTBOUND_CONNECT = '/v1/mgmt/outbound/app/connect';

// --- grant types -------------------------------------------------------------

export const GRANT_CLIENT_CREDENTIALS = 'client_credentials';
export const GRANT_REFRESH_TOKEN = 'refresh_token';
export const GRANT_DEVICE_CODE = 'urn:ietf:params:oauth:grant-type:device_code';
export const GRANT_CIBA = 'urn:openid:params:grant-type:ciba';
// Exchange a signed external JWT (from a Descope-registered trusted issuer)
// for a Descope token; the client must enable JWT Bearer + register the issuer.
export const GRANT_JWT_BEARER = 'urn:ietf:params:oauth:grant-type:jwt-bearer';

// Resource tokens are minted by exchanging the agent's Descope access token for a
// Resource-scoped token via the RFC 8693 token-exchange grant against OAUTH2_TOKEN.
export const GRANT_TOKEN_EXCHANGE = 'urn:ietf:params:oauth:grant-type:token-exchange';
export const TOKEN_TYPE_ACCESS_TOKEN = 'urn:ietf:params:oauth:token-type:access_token';
