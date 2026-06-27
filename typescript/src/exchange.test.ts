import nock from 'nock';
import { AgentAuthClient } from './client';
import { BASE_URL, PROJECT_ID, makeClient, tokenObj } from './testutils';
import { ClientCredentialsProvider, ManagementKeyProvider } from './providers';
import { AgentAuthError, PolicyDenied, TokenExchangeFailed } from './errors';

const TOKEN_PATH = '/oauth2/v1/token';
const USER_LATEST = '/v1/mgmt/outbound/app/user/token/latest';
const USER_SCOPED = '/v1/mgmt/outbound/app/user/token';
const TENANT_LATEST = '/v1/mgmt/outbound/app/tenant/token/latest';
const TENANT_SCOPED = '/v1/mgmt/outbound/app/tenant/token';
const CONNECT_PATH = '/v1/mgmt/outbound/app/connect';

const silentLogger = { debug: () => {}, warn: () => {} };

beforeAll(() => {
  nock.disableNetConnect();
});

afterEach(() => {
  nock.cleanAll();
});

afterAll(() => {
  nock.enableNetConnect();
});

/** A client whose phase-1 credential acquisition is already stubbed. */
const agentClient = (): AgentAuthClient => {
  nock(BASE_URL).post(TOKEN_PATH).reply(200, { access_token: 'agent_at', expires_in: 3600 });
  return makeClient(new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }));
};

const mgmtClient = (): AgentAuthClient =>
  makeClient(
    new ManagementKeyProvider({
      managementKey: 'K123',
      allowManagementKey: true,
      logger: silentLogger,
    }),
  );

describe('ConnectionsClient.getToken', () => {
  it('omitted scopes -> /latest, carries the agent bearer header', async () => {
    let auth: string | undefined;
    let sentBody: any;
    nock(BASE_URL)
      .post(USER_LATEST, (body) => {
        sentBody = body;
        return true;
      })
      .reply(function reply() {
        auth = this.req.headers.authorization as string;
        return [200, { token: tokenObj() }];
      });

    const client = agentClient();
    const tok = await client.connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
    });
    expect(tok.accessToken).toBe('gho_downstream_token');
    expect(sentBody.scopes).toBeUndefined();
    expect(auth).toBe(`Bearer ${PROJECT_ID}:agent_at`);
  });

  it('explicit scopes -> scoped endpoint, full override', async () => {
    let sentBody: any;
    nock(BASE_URL)
      .post(USER_SCOPED, (body) => {
        sentBody = body;
        return true;
      })
      .reply(200, { token: tokenObj({ scopes: ['repo', 'read:org'] }) });

    const client = agentClient();
    const tok = await client.connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
      scopes: ['repo', 'read:org'],
    });
    expect(tok.scopes).toEqual(['repo', 'read:org']);
    expect(sentBody.scopes).toEqual(['repo', 'read:org']);
  });

  it('404 -> ConnectionAuthorizationRequired carrying the connect URL', async () => {
    nock(BASE_URL).post(USER_LATEST).reply(404, { error: 'not found' });
    nock(BASE_URL).post(CONNECT_PATH).reply(200, { url: 'https://api.descope.com/connect?x=1' });

    const client = agentClient();
    await expect(
      client.connections.getToken({ connection: 'github', identifier: 'user@example.com' }),
    ).rejects.toMatchObject({
      name: 'ConnectionAuthorizationRequired',
      connectUrl: 'https://api.descope.com/connect?x=1',
      connection: 'github',
    });
  });

  it('404 with no resolvable connect URL -> connectUrl undefined', async () => {
    nock(BASE_URL).post(USER_SCOPED).reply(404, { error: 'not found' });
    nock(BASE_URL).post(CONNECT_PATH).reply(500, { error: 'nope' }).persist();
    const client = agentClient();
    await expect(
      client.connections.getToken({
        connection: 'github',
        identifier: 'user@example.com',
        scopes: ['repo'],
      }),
    ).rejects.toMatchObject({ name: 'ConnectionAuthorizationRequired', connectUrl: undefined });
  });

  it('connect request nests scopes + extra fields under options', async () => {
    const client = agentClient();
    let connectBody: any;
    nock(BASE_URL).post(USER_SCOPED).reply(404, { error: 'no' });
    nock(BASE_URL)
      .post(CONNECT_PATH, (b) => {
        connectBody = b;
        return true;
      })
      .reply(200, { url: 'https://api.descope.com/connect' });

    await client.connections
      .getToken({
        connection: 'github',
        identifier: 'user@example.com',
        scopes: ['repo'],
        redirectUrl: 'https://app/cb',
        connectOptions: { prompt: ['consent'] },
      })
      .catch(() => undefined);

    expect(connectBody.options.scopes).toEqual(['repo']);
    expect(connectBody.options.redirectUrl).toBe('https://app/cb');
    expect(connectBody.options.prompt).toEqual(['consent']);
    expect(connectBody.scopes).toBeUndefined(); // not at top level
  });

  it('403 -> PolicyDenied', async () => {
    nock(BASE_URL).post(USER_LATEST).reply(403, { error: 'policy denied' });
    const client = agentClient();
    await expect(
      client.connections.getToken({ connection: 'github', identifier: 'user@example.com' }),
    ).rejects.toBeInstanceOf(PolicyDenied);
  });

  it('500 -> TokenExchangeFailed', async () => {
    // 500 is a retryable status; the exchange retries up to 3 times.
    nock(BASE_URL).post(USER_LATEST).times(3).reply(500, { error: 'boom' });
    const client = agentClient();
    await expect(
      client.connections.getToken({ connection: 'github', identifier: 'user@example.com' }),
    ).rejects.toBeInstanceOf(TokenExchangeFailed);
  });

  it('management key -> unrestricted exchange with key bearer header', async () => {
    let auth: string | undefined;
    nock(BASE_URL)
      .post(USER_LATEST)
      .reply(function reply() {
        auth = this.req.headers.authorization as string;
        return [200, { token: tokenObj() }];
      });
    const client = mgmtClient();
    const tok = await client.connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
    });
    expect(tok.accessToken).toBe('gho_downstream_token');
    expect(auth).toBe(`Bearer ${PROJECT_ID}:K123`);
  });

  it('caches downstream tokens (second call served from cache)', async () => {
    const scope = nock(BASE_URL).post(USER_LATEST).reply(200, { token: tokenObj() });
    const client = agentClient();
    await client.connections.getToken({ connection: 'github', identifier: 'user@example.com' });
    await client.connections.getToken({ connection: 'github', identifier: 'user@example.com' });
    expect(scope.isDone()).toBe(true); // only one interceptor consumed
  });

  it('threads tenantId into the user-token body', async () => {
    let sentBody: any;
    nock(BASE_URL)
      .post(USER_LATEST, (b) => {
        sentBody = b;
        return true;
      })
      .reply(200, { token: tokenObj() });
    const client = agentClient();
    await client.connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
      tenantId: 't1',
    });
    expect(sentBody.tenantId).toBe('t1');
  });

  it('same user + different tenant do not collide in cache', async () => {
    // One token per tenant for the same Connection; each distinct tenant hits net.
    nock(BASE_URL).post(USER_LATEST).reply(200, { token: tokenObj() });
    nock(BASE_URL).post(USER_LATEST).reply(200, { token: tokenObj() });
    const client = mgmtClient();
    await client.connections.getToken({
      connection: 'github',
      identifier: 'u@x.com',
      tenantId: 't1',
    });
    await client.connections.getToken({
      connection: 'github',
      identifier: 'u@x.com',
      tenantId: 't2',
    });
    expect(nock.pendingMocks()).toHaveLength(0); // both interceptors consumed
  });
});

describe('ConnectionsClient.getTenantToken', () => {
  it('omitted scopes -> tenant /latest with tenantId, no userId', async () => {
    let sentBody: any;
    nock(BASE_URL)
      .post(TENANT_LATEST, (b) => {
        sentBody = b;
        return true;
      })
      .reply(200, { token: tokenObj() });
    const client = agentClient();
    const tok = await client.connections.getTenantToken({ connection: 'github', tenantId: 't1' });
    expect(tok.accessToken).toBe('gho_downstream_token');
    expect(sentBody.tenantId).toBe('t1');
    expect(sentBody.userId).toBeUndefined();
  });

  it('explicit scopes -> tenant scoped endpoint', async () => {
    let sentBody: any;
    nock(BASE_URL)
      .post(TENANT_SCOPED, (b) => {
        sentBody = b;
        return true;
      })
      .reply(200, { token: tokenObj({ scopes: ['read'] }) });
    const client = agentClient();
    await client.connections.getTenantToken({
      connection: 'github',
      tenantId: 't1',
      scopes: ['read'],
    });
    expect(sentBody.scopes).toEqual(['read']);
  });

  it('miss -> ConnectionAuthorizationRequired with no connect URL and no connect call', async () => {
    nock(BASE_URL).post(TENANT_LATEST).reply(404, { error: 'not found' });
    // Deliberately NOT registering a CONNECT interceptor: if the SDK tried to
    // build a connect URL, nock would throw on the unmatched request.
    const client = agentClient();
    await expect(
      client.connections.getTenantToken({ connection: 'github', tenantId: 't1' }),
    ).rejects.toMatchObject({ name: 'ConnectionAuthorizationRequired', connectUrl: undefined });
  });
});

describe('ConnectionsClient.waitForConnection', () => {
  it('polls until connected, delivering the connect URL once', async () => {
    nock(BASE_URL).post(USER_LATEST).reply(404, { error: 'no' });
    nock(BASE_URL).post(CONNECT_PATH).reply(200, { url: 'https://api.descope.com/connect' });
    nock(BASE_URL).post(USER_LATEST).reply(200, { token: tokenObj() });

    const client = agentClient();
    const delivered: string[] = [];
    const tok = await client.connections.waitForConnection({
      connection: 'github',
      identifier: 'u@x.com',
      onConnectUrl: (u) => delivered.push(u),
      pollIntervalSeconds: 0,
      timeoutSeconds: 5,
    });

    expect(tok.accessToken).toBe('gho_downstream_token');
    expect(delivered).toEqual(['https://api.descope.com/connect']); // delivered once
  });

  it('throws on timeout', async () => {
    nock(BASE_URL).post(USER_LATEST).reply(404, { error: 'no' });
    nock(BASE_URL).post(CONNECT_PATH).reply(200, { url: 'https://api.descope.com/connect' });
    const client = agentClient();
    await expect(
      client.connections.waitForConnection({
        connection: 'github',
        identifier: 'u@x.com',
        timeoutSeconds: 0,
      }),
    ).rejects.toBeInstanceOf(AgentAuthError);
  });
});

describe('AgentAuthClient', () => {
  it("constructs in mode='execute' but disables raw token fetch (seam)", async () => {
    const client = new AgentAuthClient({
      projectId: PROJECT_ID,
      baseUrl: BASE_URL,
      mode: 'execute',
      credential: new ManagementKeyProvider({
        managementKey: 'K',
        allowManagementKey: true,
        logger: silentLogger,
      }),
    });
    expect(client.mode).toBe('execute');
    await expect(
      client.connections.getToken({ connection: 'github', identifier: 'user@example.com' }),
    ).rejects.toBeInstanceOf(AgentAuthError);
  });
});
