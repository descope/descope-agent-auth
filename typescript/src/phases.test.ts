import nock from 'nock';
import { AgentAuthClient } from './client';
import { BASE_URL, PROJECT_ID, makeClient, tokenObj } from './testutils';
import { CibaProvider, ManagementKeyProvider } from './providers';
import { withConnection } from './tools';
import { AgentAuthError, ApprovalDenied, ConnectionAuthorizationRequired } from './errors';

// Make CIBA polling instant.
jest.mock('./httpClient', () => {
  const actual = jest.requireActual('./httpClient');
  return { ...actual, sleep: () => Promise.resolve() };
});

const USER_LATEST = '/v1/mgmt/outbound/app/user/token/latest';
const CONNECT_PATH = '/v1/mgmt/outbound/app/connect';
const CIBA_PATH = '/oauth2/v1/ciba/auth';
const TOKEN_PATH = '/oauth2/v1/token';
const silentLogger = { debug: () => {}, warn: () => {} };

const mgmt = () =>
  new ManagementKeyProvider({ managementKey: 'K', allowManagementKey: true, logger: silentLogger });

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

describe('CIBA approval gate', () => {
  const clientWithApproval = (): AgentAuthClient =>
    new AgentAuthClient({
      projectId: PROJECT_ID,
      baseUrl: BASE_URL,
      credential: mgmt(),
      approval: new CibaProvider({ clientId: 'cid', loginHint: 'user@example.com' }),
    });

  it('proceeds with the exchange after approval', async () => {
    nock(BASE_URL)
      .post(CIBA_PATH)
      .reply(200, { auth_req_id: 'areq', interval: 1, expires_in: 60 })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'approval_at', expires_in: 3600 });
    nock(BASE_URL).post(USER_LATEST).reply(200, { token: tokenObj() });

    const tok = await clientWithApproval().connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
      requireApproval: { loginHint: 'user@example.com', bindingMessage: 'Approve repo access' },
    });
    expect(tok.accessToken).toBe('gho_downstream_token');
  });

  it('blocks the exchange when denied', async () => {
    nock(BASE_URL)
      .post(CIBA_PATH)
      .reply(200, { auth_req_id: 'areq', interval: 1, expires_in: 60 })
      .post(TOKEN_PATH)
      .reply(400, { error: 'access_denied' });
    // No USER_LATEST interceptor: the exchange must never run.

    await expect(
      clientWithApproval().connections.getToken({
        connection: 'github',
        identifier: 'user@example.com',
        requireApproval: { loginHint: 'user@example.com' },
      }),
    ).rejects.toBeInstanceOf(ApprovalDenied);
  });

  it('errors when requireApproval is set but no provider is configured', async () => {
    const client = makeClient(mgmt()); // no approval provider
    await expect(
      client.connections.getToken({
        connection: 'github',
        identifier: 'user@example.com',
        requireApproval: { loginHint: 'user@example.com' },
      }),
    ).rejects.toBeInstanceOf(AgentAuthError);
  });
});

describe('withConnection tool wrapper', () => {
  it('injects the scoped token', async () => {
    nock(BASE_URL).post('/v1/mgmt/outbound/app/user/token').reply(200, { token: tokenObj() });
    const client = makeClient(mgmt());

    const listRepos = withConnection(
      client,
      { connection: 'github', scopes: ['repo'] },
      async (token, identifier) => `${identifier}:${token}`,
    );

    expect(await listRepos('user@example.com')).toBe('user@example.com:gho_downstream_token');
  });

  it('surfaces the re-auth signal', async () => {
    nock(BASE_URL).post('/v1/mgmt/outbound/app/user/token').reply(404, { error: 'nope' });
    nock(BASE_URL).post(CONNECT_PATH).reply(200, { url: 'https://api.descope.com/connect?x=1' });
    const client = makeClient(mgmt());

    const listRepos = withConnection(
      client,
      { connection: 'github', scopes: ['repo'] },
      async (token) => token,
    );

    const err = await listRepos('user@example.com').catch((e) => e);
    expect(err).toBeInstanceOf(ConnectionAuthorizationRequired);
    expect(err.connectUrl).toBe('https://api.descope.com/connect?x=1');
  });
});

describe('execution seam', () => {
  it('fetch mode returns a token', async () => {
    nock(BASE_URL).post(USER_LATEST).reply(200, { token: tokenObj() });
    const client = makeClient(mgmt()); // default fetch mode
    const tok = await client.connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
    });
    expect(tok.accessToken).toBe('gho_downstream_token');
  });

  it('execute mode disables raw token fetch', async () => {
    const client = makeClient(mgmt(), { mode: 'execute' });
    await expect(
      client.connections.getToken({ connection: 'github', identifier: 'user@example.com' }),
    ).rejects.toBeInstanceOf(AgentAuthError);
  });

  it('execute() is stubbed and routes no raw token (execute mode)', async () => {
    const client = makeClient(mgmt(), { mode: 'execute' });
    await expect(
      client.connections.execute({
        request: { method: 'GET', url: 'https://api.github.com/user' },
        connection: 'github',
        identifier: 'user@example.com',
      }),
    ).rejects.toThrow(/hosted execution endpoint/);
  });

  it('execute() requires execute mode', async () => {
    const client = makeClient(mgmt()); // fetch mode
    await expect(
      client.connections.execute({
        request: { method: 'GET', url: 'https://api.github.com/user' },
        connection: 'github',
        identifier: 'user@example.com',
      }),
    ).rejects.toBeInstanceOf(AgentAuthError);
  });
});
