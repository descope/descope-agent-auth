# SDK reference

Every public symbol in `descope-agent-auth` (Python) / `@descope/agent-auth`
(TypeScript). TypeScript names are the camelCase of the Python ones unless noted.

The shape is always: **configure a client once** (how the agent authenticates to
Descope), then **fetch tokens repeatedly**. All fetches refresh transparently.

## Clients

| | Python | TypeScript |
| --- | --- | --- |
| Sync | `AgentAuthClient` | `AgentAuthClient` (methods are async) |
| Async | `AsyncAgentAuthClient` | — (the TS client is already async) |

```python
AgentAuthClient(
    *, project_id, credential,
    base_url="https://api.descope.com",
    store=None,            # TokenStore; defaults to MemoryTokenStore
    approval=None,         # CibaProvider, to gate calls with require_approval
    timeout=30.0, retry=None, logger=None,
    cache_tokens=True,     # False -> every fetch re-enforces Policies
)
```

Methods: `get_credential()`, `refresh_credential()`, `close()` (async: `aclose()`),
context-manager support, and the two token-fetch entry points `.connections` and
`.resources`.

## Connections — `client.connections`

Tokens stored in the Descope Connections vault (provider OAuth tokens or API keys).

| Method | Returns | Purpose |
| --- | --- | --- |
| `get_token(*, connection, identifier, scopes=None, tenant_id=None, with_refresh_token=False, force_refresh=False, redirect_url=None, connect_options=None, require_approval=None, act_as_user_token=None)` | `VaultToken` | Fetch a **user-level** token. Raises `ConnectionAuthorizationRequired` if the user hasn't connected. |
| `get_tenant_token(*, connection, tenant_id, scopes=None, with_refresh_token=False, force_refresh=False, require_approval=None, act_as_user_token=None)` | `VaultToken` | Fetch a **tenant-level** (org-shared) token. |
| `get_connect_url(*, connection, identifier, scopes=None, tenant_id=None, redirect_url=None, connect_options=None, act_as_user_token=None)` | `str \| None` | Generate the URL to send a user through to authorize the connection (the proactive form of catching `ConnectionAuthorizationRequired`). |
| `wait_for_connection(*, connection, identifier, scopes=None, tenant_id=None, act_as_user_token=None, poll_interval=2.0, timeout=300.0)` | `VaultToken` | Poll `get_token` until the user finishes connecting. |

`scopes` overrides the Connection defaults; `act_as_user_token` runs one call as a
specific user; `tenant_id` selects a user's per-tenant token. TS: `getToken`,
`getTenantToken`, `getConnectUrl`, `waitForConnection`, `execute` (camelCased args).

## Resources — `client.resources`

Descope-issued OAuth tokens for **your own** APIs, minted via token-exchange.

| Method | Returns | Purpose |
| --- | --- | --- |
| `get_token(*, resource, scopes=None, audience=None, require_approval=None, force_refresh=False, act_as_user_token=None)` | `VaultToken` | Mint a Resource token. `resource` is the RFC 8707 indicator; `audience` sets the RFC 8693 audience claim. A **user** token (`act_as_user_token`) → user-scoped; client credentials → client-scoped. |

## Sign-in providers

How the agent authenticates to Descope. Pass one as `credential=`.

| Provider | Constructor | Use when |
| --- | --- | --- |
| `ClientCredentialsProvider` | `(*, client_id, client_secret, scopes=None)` | autonomous agent, no user |
| `DeviceCodeProvider` | `(*, client_id, scopes=None, on_pending=None, max_wait_seconds=300.0)` | headless/CLI agent (no browser) |
| `CibaProvider` | `(*, client_id, login_hint, client_secret=None, binding_message=None, scopes=None, max_wait_seconds=120.0)` | out-of-band user approval; also the `approval=` gate |
| `AccessTokenProvider` | `(*, access_token, expires_at=None, refresh_token=None)` | you already hold a user's Descope token |
| `JwtBearerProvider` | `(*, client_id, assertion, scopes=None)` | exchange a signed JWT from a trusted issuer (RFC 7523); `assertion` may be a string or a callable |
| `ManagementKeyProvider` | `(*, management_key, allow_management_key=False)` | privileged, **not recommended** (bypasses Policies) |

### Ask the user to approve a specific action (RFC 9396)

`CibaProvider.authenticate(*, login_hint, binding_message=None, scopes=None, timeout_seconds=None, resource=None, authorization_details=None)`
(`timeout_seconds=None` waits up to the provider's `max_wait_seconds`)
(TS: `authenticate({ loginHint, bindingMessage?, scopes?, timeoutSeconds?, resource?, authorizationDetails? })`)
runs one CIBA cycle. With `authorization_details` the user approves that exact action,
and the returned `Credential` carries what they approved:

```python
cred = await ciba.authenticate(
    login_hint="alice@example.com",
    binding_message="Pay EUR 15.00 to Acme",
    resource="https://api.bank.example.com",
    authorization_details=[{"type": "payment_initiation", "amount": "15.00", "currency": "EUR"}],
)
cred.authorization_details  # the approved grant, from the /token response
```

The same two fields on `ApprovalRequest` gate a single call with `require_approval=`.

- **One approval per call.** A credential obtained with `authorization_details` is never
  cached or stored: every call asks the user again. Plain CIBA (`get_credential()`)
  keeps its caching. Its `refresh_token`, if returned, stays a handle to the same grant
  (RFC 9396 section 6), so refreshing keeps the approved details; enforcing single use
  (e.g. a payment executed once) is the resource server's job.
- **One resource, one element.** `resource` is a single string. Descope accepts one
  `authorization_details` element, up to 4096 bytes and 5 levels deep, whose `type` is
  registered on `resource`; anything else raises `InvalidAuthorizationDetails` before
  any approval is sent. Details without a `resource` are rejected the same way.
- **Console prerequisites.** A Resource with the RAR type registered; an inbound app
  with CIBA enabled and a CIBA approval flow that shows the details (e.g.
  `{{authorizationDetails.payment_initiation.amount}}`); a user-access rule on the
  Resource. To put the grant on the access token, add a Custom Claims action
  (`authorization_details` <- `{{authorizationDetails}}`) before CIBA Approval; the
  id_token never carries it.

## Tool wrapper

| Python | TypeScript | Purpose |
| --- | --- | --- |
| `with_connection(client, *, connection, scopes=None, tenant_id=None, require_approval=None)` | `withConnection(client, { connection, scopes?, tenantId?, requireApproval? }, fn)` | Decorate/wrap a tool so a fresh scoped token is injected. |
| `with_connection_async(...)` | — (TS `withConnection` is already async) | Async counterpart. |

Also `langgraph_connection_tool` / `langgraphConnectionTool` for LangGraph `interrupt()`.

## Token store

`TokenStore` (abstract): implement `get`, `set`, `delete`, `list` over Redis/DB/etc.
for cross-restart, multi-process persistence. `MemoryTokenStore` is the in-process
default.

## Errors

All extend `AgentAuthError`; match with `isinstance` / `instanceof`.

| Error | Meaning |
| --- | --- |
| `ConnectionAuthorizationRequired` | user hasn't connected; carries `connect_url` / `connectUrl`, `connection`, `identifier` |
| `PolicyDenied` | the credential lacks Policy permission |
| `ApprovalDenied` / `ApprovalTimeout` | a CIBA approval gate was rejected / timed out |
| `CredentialAcquisitionFailed` | the agent couldn't sign in to Descope |
| `InvalidAuthorizationDetails` | Descope rejected (or didn't apply) a CIBA request's `authorization_details`; carries the server's `error_description` / `errorDescription`. Subclass of `CredentialAcquisitionFailed`; fix the request, don't retry |
| `TokenExchangeFailed` | other token-fetch failure |

## Types

- `VaultToken` — `access_token`, `token_type`, `expires_at`, `scopes`, `refresh_token`,
  `has_refresh_token`, `app_id`, `user_id`, `raw` (TS: camelCase). `str()` never leaks
  the token.
- `Credential` — the agent's Descope sign-in credential (`token`, `kind`, `expires_at`,
  `refresh_token`, `scope`, `authorization_details`).
- `ApprovalRequest` — `login_hint`, `binding_message`, `scopes`, `timeout_seconds`,
  `resource`, `authorization_details`.
- `PendingAuthorization` — device-code / CIBA "user action required" details.
- `CredentialKind` — `"agent_token"` | `"management_key"`.
