import nock from 'nock';
import { AgentAuthClient } from './client';
import { BASE_URL, PROJECT_ID } from './testutils';
import {
  CibaProvider,
  ClientCredentialsProvider,
  DeviceCodeProvider,
  ManagementKeyProvider,
} from './providers';
import { MemoryTokenStore } from './store';

// Make polling instant where relevant.
jest.mock('./httpClient', () => {
  const actual = jest.requireActual('./httpClient');
  return { ...actual, sleep: () => Promise.resolve() };
});

const TOKEN_PATH = '/oauth2/v1/token';
const silentLogger = { debug: () => {}, warn: () => {} };

const client = (credential: any, store: MemoryTokenStore) =>
  new AgentAuthClient({ projectId: PROJECT_ID, baseUrl: BASE_URL, credential, store });

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

describe('phase-1 credential persistence', () => {
  it('persists the credential and reuses it across instances (restart)', async () => {
    nock(BASE_URL).post(TOKEN_PATH).reply(200, { access_token: 'agent_at', expires_in: 3600 });
    const store = new MemoryTokenStore();

    const first = client(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
      store,
    );
    expect((await first.getCredential()).token).toBe('agent_at');

    // A fresh client/provider backed by the same store loads from it — no 2nd call.
    // (No second nock interceptor is registered, so any HTTP call would throw.)
    const second = client(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
      store,
    );
    expect((await second.getCredential()).token).toBe('agent_at');
    expect(store.list()).toContain(`cred:client_credentials:${PROJECT_ID}:cid`);
  });

  it('does not persist a management key', async () => {
    const store = new MemoryTokenStore();
    const c = client(
      new ManagementKeyProvider({
        managementKey: 'K',
        allowManagementKey: true,
        logger: silentLogger,
      }),
      store,
    );
    await c.getCredential();
    expect(store.list()).toEqual([]);
  });
});

describe('refresh from a stored token (no re-auth)', () => {
  it('device: refreshes a stored expired token with client_id, without re-running the flow', async () => {
    const store = new MemoryTokenStore();
    store.set(
      `cred:device:${PROJECT_ID}:cid`,
      JSON.stringify({
        token: 'old',
        kind: 'agent_token',
        expiresAt: Date.now() / 1000 - 100,
        refreshToken: 'r1',
      }),
    );
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'new', expires_in: 3600 });

    const cred = await client(new DeviceCodeProvider({ clientId: 'cid' }), store).getCredential();

    expect(cred.token).toBe('new');
    expect(body.grant_type).toBe('refresh_token');
    expect(body.client_id).toBe('cid'); // device refresh needs client_id
  });

  it('ciba: refresh includes client_id and client_secret', async () => {
    const store = new MemoryTokenStore();
    store.set(
      `cred:ciba:${PROJECT_ID}:cid:user@example.com`,
      JSON.stringify({
        token: 'old',
        kind: 'agent_token',
        expiresAt: Date.now() / 1000 - 100,
        refreshToken: 'r1',
      }),
    );
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'new', expires_in: 3600 });

    const provider = new CibaProvider({
      clientId: 'cid',
      clientSecret: 'sec',
      loginHint: 'user@example.com',
    });
    await client(provider, store).getCredential();

    expect(body.grant_type).toBe('refresh_token');
    expect(body.client_id).toBe('cid');
    expect(body.client_secret).toBe('sec');
  });

  it('persists a rotated refresh token', async () => {
    const store = new MemoryTokenStore();
    const key = `cred:device:${PROJECT_ID}:cid`;
    store.set(
      key,
      JSON.stringify({
        token: 'old',
        kind: 'agent_token',
        expiresAt: Date.now() / 1000 - 100,
        refreshToken: 'r1',
      }),
    );
    nock(BASE_URL)
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'new', expires_in: 3600, refresh_token: 'r2' });

    await client(new DeviceCodeProvider({ clientId: 'cid' }), store).getCredential();

    const stored = JSON.parse(store.get(key) as string);
    expect(stored.token).toBe('new');
    expect(stored.refreshToken).toBe('r2');
  });
});
