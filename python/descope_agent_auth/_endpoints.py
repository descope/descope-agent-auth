"""Centralized Descope endpoint paths and grant-type constants.

Every wire path the SDK touches lives here so it can be confirmed against the
Descope API reference in one place (per the spec's note to the implementer).
Paths are relative to the configured ``base_url`` (default ``https://api.descope.com``).

Verification status as of build (2026-06):
  VERIFIED against docs.descope.com:
    - outbound user/tenant token fetch endpoints
    - outbound connect (connect-URL) endpoint
    - oauth2 token + authorize endpoints
    - device_code grant-type string
  UNVERIFIED -- confirm against the project's OIDC discovery document
  (``/<project_id>/.well-known/openid-configuration``) before relying on them:
    - DEVICE_AUTHORIZATION path
    - CIBA backchannel path
    - CIBA grant-type string
    - RESOURCE token endpoint shape
These are isolated as named constants precisely so confirming/overriding them is a
one-line change, not a refactor.
"""

from __future__ import annotations

# --- Phase 1: OAuth2 / OIDC (acquisition) -----------------------------------

# VERIFIED. Used for authorization_code (+PKCE), client_credentials, refresh_token,
# device_code, and CIBA token-polling grants.
OAUTH2_TOKEN = "/oauth2/v1/token"

# VERIFIED. Authorization-code redirect entry point.
OAUTH2_AUTHORIZE = "/oauth2/v1/authorize"

# VERIFIED (inbound-apps authorization server). Alternative token endpoint when the
# agent authenticates as an inbound app client rather than the project OIDC server.
OAUTH2_APPS_TOKEN = "/oauth2/v1/apps/token"

# UNVERIFIED -- confirm via discovery (device_authorization_endpoint).
DEVICE_AUTHORIZATION = "/oauth2/v1/device"

# UNVERIFIED -- confirm via discovery (backchannel_authentication_endpoint).
CIBA_AUTHENTICATE = "/oauth2/v1/ciba/auth"

# OIDC discovery document (project-scoped). VERIFIED shape.
def discovery(project_id: str) -> str:
    return f"/{project_id}/.well-known/openid-configuration"


# --- Phase 2: vault exchange -------------------------------------------------

# VERIFIED. Fetch the latest stored outbound-app user token (uses Connection defaults).
OUTBOUND_USER_TOKEN_LATEST = "/v1/mgmt/outbound/app/user/token/latest"

# VERIFIED. Fetch a stored outbound-app user token for an explicit scope set.
OUTBOUND_USER_TOKEN = "/v1/mgmt/outbound/app/user/token"

# VERIFIED. Tenant-scoped variants (used for resource/tenant tokens).
OUTBOUND_TENANT_TOKEN_LATEST = "/v1/mgmt/outbound/app/tenant/token/latest"
OUTBOUND_TENANT_TOKEN = "/v1/mgmt/outbound/app/tenant/token"

# VERIFIED. Request a connect URL the user visits to authorize a connection.
OUTBOUND_CONNECT = "/v1/mgmt/outbound/app/connect"


# --- grant types -------------------------------------------------------------

GRANT_CLIENT_CREDENTIALS = "client_credentials"
GRANT_AUTHORIZATION_CODE = "authorization_code"
GRANT_REFRESH_TOKEN = "refresh_token"
GRANT_DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"  # VERIFIED
GRANT_CIBA = "urn:openid:params:grant-type:ciba"  # UNVERIFIED -- confirm via discovery
