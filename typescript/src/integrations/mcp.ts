/**
 * MCP integration: feed Descope-vaulted tokens into an MCP client's OAuth seam.
 *
 * The MCP spec defines a pluggable `OAuthClientProvider` that an MCP *client* uses
 * to obtain the token it sends to a remote MCP *server*. Normally the client runs
 * the whole OAuth dance itself (discovery, DCR, the authorization-code redirect,
 * storage, refresh). In a *brokered* model, Descope already holds and refreshes that
 * token in the vault — so this provider short-circuits the dance: `tokens()` returns
 * the vaulted token and the rest are deliberate no-ops.
 *
 * The object returned is structurally compatible with the `OAuthClientProvider` in
 * `@modelcontextprotocol/sdk` and the `authProvider` accepted by `@ai-sdk/mcp`'s
 * `createMCPClient` — so you can pass it straight in, and this package keeps a zero
 * dependency on the MCP SDK.
 *
 *     import { createMCPClient } from '@ai-sdk/mcp';
 *     import { descopeMcpConnectionAuthProvider } from '@descope/agent-auth';
 *
 *     const mcp = await createMCPClient({
 *       transport: {
 *         type: 'http',
 *         url: 'https://mcp.linear.app',
 *         authProvider: descopeMcpConnectionAuthProvider(client, {
 *           connection: 'linear',
 *           identifier: userId,        // resolved server-side, never from the model
 *         }),
 *       },
 *     });
 *
 * When the user hasn't connected the provider yet, `tokens()` throws
 * `ConnectionAuthorizationRequired` (carrying `connectUrl`) — catch it where you run
 * the agent and redirect the user to consent, exactly as you would for a direct
 * `connections.getToken` call. After they consent, the next call just works.
 *
 * Two flavors, matching the two token types:
 *  - `descopeMcpConnectionAuthProvider` — the MCP server is protected by a provider
 *    you've set up as a Descope Connection (the token is that provider's own token).
 *  - `descopeMcpResourceAuthProvider` — the MCP server treats Descope as its OAuth
 *    authorization server (the token is a Descope-minted Resource token).
 */

import type { AgentAuthClient } from '../client';
import type { ApprovalRequest } from '../types';

/** Minimal OAuth token shape the MCP transports read (subset of MCP's `OAuthTokens`). */
export interface McpOAuthTokens {
  access_token: string;
  token_type: string;
  scope?: string;
}

/**
 * The subset of the MCP-spec `OAuthClientProvider` a brokered provider implements.
 * Structurally assignable to the real interface, so it can be passed to `authProvider`
 * without importing `@modelcontextprotocol/sdk`.
 */
export interface McpAuthProvider {
  readonly redirectUrl: string | URL | undefined;
  readonly clientMetadata: { redirect_uris: string[] };
  clientInformation(): undefined;
  tokens(): Promise<McpOAuthTokens>;
  saveTokens(): void;
  redirectToAuthorization(): void;
  saveCodeVerifier(): void;
  codeVerifier(): string;
}

export interface McpConnectionAuthOptions {
  /** The Descope Connection / Outbound App name (e.g. `'linear'`, `'github'`). */
  connection: string;
  /** The user the agent acts for. Resolve this server-side — never from model input. */
  identifier: string;
  /** Override the Connection's default scopes (fully replaces them when set). */
  scopes?: string[];
  /** Select a user's per-tenant token. */
  tenantId?: string;
  /** Act as a specific user on a shared client (the user's Descope access token). */
  actAsUserToken?: string;
  /** Require a fresh CIBA approval (needs an `approval` provider on the client). */
  requireApproval?: ApprovalRequest;
  /** Reported as the provider's `redirectUrl`; the brokered flow doesn't use it. */
  redirectUrl?: string;
}

export interface McpResourceAuthOptions {
  /** RFC 8707 resource indicator for the API the MCP server represents. */
  resource: string;
  scopes?: string[];
  /** Token-exchange `audience` claim, when the resource requires it. */
  audience?: string[];
  actAsUserToken?: string;
  /** Require a fresh CIBA approval (needs an `approval` provider on the client). */
  requireApproval?: ApprovalRequest;
}

const brokeredProvider = (
  fetchToken: () => Promise<{ accessToken: string; tokenType: string; scopes: string[] }>,
  redirectUrl?: string,
): McpAuthProvider => ({
  // Consent is surfaced via the thrown ConnectionAuthorizationRequired, so the SDK's
  // own redirect machinery is never driven — these stay no-ops by design.
  get redirectUrl() {
    return redirectUrl;
  },
  get clientMetadata() {
    return { redirect_uris: redirectUrl ? [redirectUrl] : [] };
  },
  clientInformation() {
    return undefined;
  },
  async tokens() {
    const t = await fetchToken();
    return {
      access_token: t.accessToken,
      token_type: t.tokenType || 'bearer',
      scope: t.scopes.length ? t.scopes.join(' ') : undefined,
    };
  },
  saveTokens() {
    /* Descope owns storage + refresh */
  },
  redirectToAuthorization() {
    /* brokered: consent happens at the Descope connect URL */
  },
  saveCodeVerifier() {
    /* PKCE handled inside Descope's brokered flow */
  },
  codeVerifier() {
    return '';
  },
});

/**
 * Build an MCP `authProvider` that injects a Descope **Connection** token (the
 * provider's own OAuth token) for the given user.
 */
export function descopeMcpConnectionAuthProvider(
  client: AgentAuthClient,
  options: McpConnectionAuthOptions,
): McpAuthProvider {
  return brokeredProvider(
    () =>
      client.connections.getToken({
        connection: options.connection,
        identifier: options.identifier,
        scopes: options.scopes,
        tenantId: options.tenantId,
        actAsUserToken: options.actAsUserToken,
        requireApproval: options.requireApproval,
      }),
    options.redirectUrl,
  );
}

/**
 * Build an MCP `authProvider` that injects a Descope-minted **Resource** token (for
 * an MCP server that uses Descope as its OAuth authorization server).
 */
export function descopeMcpResourceAuthProvider(
  client: AgentAuthClient,
  options: McpResourceAuthOptions,
): McpAuthProvider {
  return brokeredProvider(() =>
    client.resources.getToken({
      resource: options.resource,
      scopes: options.scopes,
      audience: options.audience,
      actAsUserToken: options.actAsUserToken,
      requireApproval: options.requireApproval,
    }),
  );
}
