import {
  descopeMcpConnectionAuthProvider,
  descopeMcpResourceAuthProvider,
} from './integrations/mcp';
import type { AgentAuthClient } from './client';
import { ConnectionAuthorizationRequired } from './errors';
import type { VaultToken } from './types';

const vaultToken = (over: Partial<VaultToken> = {}): VaultToken => ({
  accessToken: 'gh_tok',
  tokenType: 'Bearer',
  scopes: ['repo'],
  hasRefreshToken: false,
  ...over,
});

// A minimal stand-in for AgentAuthClient that records the args it was called with.
const fakeClient = (impl: {
  connection?: (args: any) => Promise<VaultToken>;
  resource?: (args: any) => Promise<VaultToken>;
}) => {
  const calls: { connection: any[]; resource: any[] } = { connection: [], resource: [] };
  const client = {
    connections: {
      getToken: (args: any) => {
        calls.connection.push(args);
        return (impl.connection ?? (() => Promise.resolve(vaultToken())))(args);
      },
    },
    resources: {
      getToken: (args: any) => {
        calls.resource.push(args);
        return (impl.resource ?? (() => Promise.resolve(vaultToken())))(args);
      },
    },
  } as unknown as AgentAuthClient;
  return { client, calls };
};

describe('descopeMcpConnectionAuthProvider', () => {
  it('maps a vaulted Connection token into MCP OAuthTokens shape', async () => {
    const { client } = fakeClient({
      connection: () =>
        Promise.resolve(
          vaultToken({ accessToken: 'real_gh', tokenType: 'Bearer', scopes: ['repo', 'read:org'] }),
        ),
    });
    const provider = descopeMcpConnectionAuthProvider(client, {
      connection: 'github',
      identifier: 'user_123',
    });

    const tokens = await provider.tokens();
    expect(tokens).toEqual({
      access_token: 'real_gh',
      token_type: 'Bearer',
      scope: 'repo read:org',
    });
  });

  it('forwards connection, identifier, scopes, tenant, and act-as-user', async () => {
    const { client, calls } = fakeClient({});
    const provider = descopeMcpConnectionAuthProvider(client, {
      connection: 'github',
      identifier: 'user_123',
      scopes: ['repo'],
      tenantId: 'acme',
      actAsUserToken: 'user_jwt',
    });

    await provider.tokens();
    expect(calls.connection[0]).toEqual({
      connection: 'github',
      identifier: 'user_123',
      scopes: ['repo'],
      tenantId: 'acme',
      actAsUserToken: 'user_jwt',
    });
  });

  it('propagates ConnectionAuthorizationRequired (consent needed) from tokens()', async () => {
    const { client } = fakeClient({
      connection: () =>
        Promise.reject(
          new ConnectionAuthorizationRequired('connect github', {
            connectUrl: 'https://connect.example/github',
            connection: 'github',
            identifier: 'user_123',
          }),
        ),
    });
    const provider = descopeMcpConnectionAuthProvider(client, {
      connection: 'github',
      identifier: 'user_123',
    });

    await expect(provider.tokens()).rejects.toBeInstanceOf(ConnectionAuthorizationRequired);
  });

  it('reports redirectUrl and clientMetadata; the rest are inert no-ops', async () => {
    const { client } = fakeClient({});
    const provider = descopeMcpConnectionAuthProvider(client, {
      connection: 'github',
      identifier: 'user_123',
      redirectUrl: 'https://app.example/callback',
    });

    expect(provider.redirectUrl).toBe('https://app.example/callback');
    expect(provider.clientMetadata).toEqual({ redirect_uris: ['https://app.example/callback'] });
    expect(provider.clientInformation()).toBeUndefined();
    expect(provider.codeVerifier()).toBe('');
    // no-ops must not throw
    expect(() => provider.saveTokens()).not.toThrow();
    expect(() => provider.redirectToAuthorization()).not.toThrow();
    expect(() => provider.saveCodeVerifier()).not.toThrow();
  });

  it('omits scope when the token carries none, and defaults token_type', async () => {
    const { client } = fakeClient({
      connection: () => Promise.resolve(vaultToken({ tokenType: '', scopes: [] })),
    });
    const provider = descopeMcpConnectionAuthProvider(client, {
      connection: 'github',
      identifier: 'u',
    });
    const tokens = await provider.tokens();
    expect(tokens).toEqual({ access_token: 'gh_tok', token_type: 'bearer', scope: undefined });
  });
});

describe('descopeMcpResourceAuthProvider', () => {
  it('mints a Resource token and forwards resource/audience/scopes', async () => {
    const { client, calls } = fakeClient({
      resource: () => Promise.resolve(vaultToken({ accessToken: 'res_at', scopes: ['read'] })),
    });
    const provider = descopeMcpResourceAuthProvider(client, {
      resource: 'urn:my-mcp',
      scopes: ['read'],
      audience: ['https://mcp.acme.com'],
    });

    const tokens = await provider.tokens();
    expect(tokens.access_token).toBe('res_at');
    expect(calls.resource[0]).toEqual({
      resource: 'urn:my-mcp',
      scopes: ['read'],
      audience: ['https://mcp.acme.com'],
      actAsUserToken: undefined,
    });
  });

  it('has no redirect target (non-interactive grant)', () => {
    const { client } = fakeClient({});
    const provider = descopeMcpResourceAuthProvider(client, { resource: 'urn:my-mcp' });
    expect(provider.redirectUrl).toBeUndefined();
    expect(provider.clientMetadata).toEqual({ redirect_uris: [] });
  });
});
