"""Centralized Descope endpoint paths and grant-type constants.

Every wire path the SDK touches lives here so it can be confirmed against the
Descope API reference in one place (per the spec's note to the implementer).
Paths are relative to the configured ``base_url`` (default ``https://api.descope.com``).

Constants marked UNVERIFIED still need confirming against the project's OIDC
discovery document (``/<project_id>/.well-known/openid-configuration``) before
relying on them:
  - DEVICE_AUTHORIZATION path
  - RESOURCE token endpoint shape
These are isolated as named constants precisely so confirming/overriding them is a
one-line change, not a refactor.
"""

from __future__ import annotations

# --- Phase 1: OAuth2 / OIDC (acquisition) -----------------------------------

# Used for client_credentials, refresh_token and device_code grants.
OAUTH2_TOKEN = "/oauth2/v1/token"

# Token endpoint for an agent that authenticates as an inbound app client rather
# than through the project OIDC server. CIBA polls here (or the
# /apps/{projectId}/token variant) because OAUTH2_TOKEN does not serve that grant.
OAUTH2_APPS_TOKEN = "/oauth2/v1/apps/token"

# UNVERIFIED -- confirm via discovery (device_authorization_endpoint).
DEVICE_AUTHORIZATION = "/oauth2/v1/device"

# CIBA is served only by the inbound-apps authorization server.
CIBA_AUTHENTICATE = "/oauth2/v1/apps/bc-authorize"

# OIDC discovery document (project-scoped).
def discovery(project_id: str) -> str:
    return f"/{project_id}/.well-known/openid-configuration"


# --- Phase 2: vault exchange -------------------------------------------------

# Fetch the latest stored outbound-app user token (uses Connection defaults).
OUTBOUND_USER_TOKEN_LATEST = "/v1/mgmt/outbound/app/user/token/latest"

# Fetch a stored outbound-app user token for an explicit scope set.
OUTBOUND_USER_TOKEN = "/v1/mgmt/outbound/app/user/token"

# Tenant-scoped Connection tokens (a tenant-level API key / org-shared
# OAuth token), distinct from Resource tokens (which use the token-exchange grant
# below). Exposed via ConnectionsClient.get_tenant_token.
OUTBOUND_TENANT_TOKEN_LATEST = "/v1/mgmt/outbound/app/tenant/token/latest"
OUTBOUND_TENANT_TOKEN = "/v1/mgmt/outbound/app/tenant/token"

# Request a connect URL the user visits to authorize a connection.
OUTBOUND_CONNECT = "/v1/mgmt/outbound/app/connect"


# --- grant types -------------------------------------------------------------

GRANT_CLIENT_CREDENTIALS = "client_credentials"
GRANT_REFRESH_TOKEN = "refresh_token"
GRANT_DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"
# Exchange a signed external JWT (from a Descope-registered trusted issuer)
# for a Descope token. The client must enable the JWT Bearer grant + register the issuer.
GRANT_JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
GRANT_CIBA = "urn:openid:params:grant-type:ciba"

# Resource tokens are minted by exchanging the agent's Descope access token for a
# Resource-scoped token via the RFC 8693 token-exchange grant against OAUTH2_TOKEN.
GRANT_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"
