import nock from 'nock';
import { BASE_URL, makeClient } from './testutils';
import {
  CibaProvider,
  ClientCredentialsProvider,
  DeviceCodeProvider,
  JwtBearerProvider,
  ManagementKeyProvider,
} from './providers';
import { ApprovalDenied, ApprovalTimeout, CredentialAcquisitionFailed } from './errors';

// Make polling instant: stub the exported sleep used by the providers.
jest.mock('./httpClient', () => {
  const actual = jest.requireActual('./httpClient');
  return { ...actual, sleep: () => Promise.resolve() };
});

const TOKEN_PATH = '/oauth2/v1/token';
const DEVICE_PATH = '/oauth2/v1/device';
const CIBA_PATH = '/oauth2/v1/ciba/auth';

beforeAll(() => {
  nock.disableNetConnect();
});

afterEach(() => {
  nock.cleanAll();
});

afterAll(() => {
  nock.enableNetConnect();
});

describe('ClientCredentialsProvider', () => {
  it('acquires a token (happy path) with Basic auth', async () => {
    let authHeader: string | undefined;
    nock(BASE_URL, {
      reqheaders: {
        authorization: (val) => {
          authHeader = val;
          return val.startsWith('Basic ');
        },
      },
    })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'agent_at', expires_in: 3600 });

    const client = makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    );
    const cred = await client.getCredential();
    expect(cred.token).toBe('agent_at');
    expect(cred.kind).toBe('agent_token');
    expect(authHeader).toMatch(/^Basic /);
  });

  it('caches the credential until expiry', async () => {
    const scope = nock(BASE_URL)
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'agent_at', expires_in: 3600 });
    const client = makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    );
    await client.getCredential();
    await client.getCredential();
    expect(scope.isDone()).toBe(true); // only one interceptor was needed
  });

  it('raises CredentialAcquisitionFailed on bad credentials', async () => {
    nock(BASE_URL).post(TOKEN_PATH).reply(401, { error: 'invalid_client' });
    const client = makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 'bad' }),
    );
    await expect(client.getCredential()).rejects.toBeInstanceOf(CredentialAcquisitionFailed);
  });

  it('uses the refresh_token grant when one is held and the token expired', async () => {
    let refreshBody: any;
    nock(BASE_URL)
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'first', expires_in: -10, refresh_token: 'r1' })
      .post(TOKEN_PATH, (body) => {
        refreshBody = body;
        return true;
      })
      .reply(200, { access_token: 'refreshed', expires_in: 3600 });
    const client = makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    );
    expect((await client.getCredential()).token).toBe('first');
    expect((await client.getCredential()).token).toBe('refreshed');
    expect(refreshBody.grant_type).toBe('refresh_token');
  });

  it('re-acquires when the cached credential is expired', async () => {
    nock(BASE_URL)
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'first', expires_in: -10 })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'second', expires_in: 3600 });
    const client = makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    );
    expect((await client.getCredential()).token).toBe('first');
    expect((await client.getCredential()).token).toBe('second');
  });
});

describe('DeviceCodeProvider', () => {
  it('polls pending then succeeds and surfaces the user code', async () => {
    nock(BASE_URL)
      .post(DEVICE_PATH)
      .reply(200, {
        device_code: 'dev123',
        user_code: 'WXYZ-1234',
        verification_uri: 'https://verify',
        interval: 1,
        expires_in: 60,
      })
      .post(TOKEN_PATH)
      .reply(400, { error: 'authorization_pending' })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'device_at', expires_in: 3600 });

    let seenCode: string | undefined;
    const provider = new DeviceCodeProvider({
      clientId: 'cid',
      onPending: (p) => {
        seenCode = p.userCode;
      },
    });
    const cred = await makeClient(provider).getCredential();
    expect(cred.token).toBe('device_at');
    expect(seenCode).toBe('WXYZ-1234');
  });

  it('honors slow_down and passes scopes', async () => {
    let sentScope: any;
    nock(BASE_URL)
      .post(DEVICE_PATH, (b) => {
        sentScope = b.scope;
        return true;
      })
      .reply(200, { device_code: 'd', interval: 1, expires_in: 60 })
      .post(TOKEN_PATH)
      .reply(400, { error: 'slow_down' })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'device_at', expires_in: 3600 });
    const provider = new DeviceCodeProvider({ clientId: 'cid', scopes: ['agent.connect'] });
    expect((await makeClient(provider).getCredential()).token).toBe('device_at');
    expect(sentScope).toBe('agent.connect');
  });

  it('times out before approval', async () => {
    nock(BASE_URL).post(DEVICE_PATH).reply(200, { device_code: 'd', interval: 1, expires_in: 0 });
    const provider = new DeviceCodeProvider({ clientId: 'cid', maxWaitSeconds: 0 });
    await expect(makeClient(provider).getCredential()).rejects.toBeInstanceOf(
      CredentialAcquisitionFailed,
    );
  });
});

describe('CibaProvider', () => {
  const initiate = () =>
    nock(BASE_URL).post(CIBA_PATH).reply(200, { auth_req_id: 'areq', interval: 1, expires_in: 60 });

  it('polls pending then approved', async () => {
    initiate()
      .post(TOKEN_PATH)
      .reply(400, { error: 'authorization_pending' })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'ciba_at', expires_in: 3600 });
    const provider = new CibaProvider({ clientId: 'cid', loginHint: 'user@example.com' });
    expect((await makeClient(provider).getCredential()).token).toBe('ciba_at');
  });

  it('honors slow_down and sends client_secret + binding_message', async () => {
    let initBody: any;
    nock(BASE_URL)
      .post(CIBA_PATH, (b) => {
        initBody = b;
        return true;
      })
      .reply(200, { auth_req_id: 'areq', interval: 1, expires_in: 60 })
      .post(TOKEN_PATH)
      .reply(400, { error: 'slow_down' })
      .post(TOKEN_PATH)
      .reply(200, { access_token: 'ciba_at', expires_in: 3600 });
    const provider = new CibaProvider({
      clientId: 'cid',
      clientSecret: 'sec',
      loginHint: 'user@example.com',
      bindingMessage: 'approve please',
    });
    expect((await makeClient(provider).getCredential()).token).toBe('ciba_at');
    expect(initBody.client_secret).toBe('sec');
    expect(initBody.binding_message).toBe('approve please');
  });

  it('raises ApprovalDenied when rejected', async () => {
    initiate().post(TOKEN_PATH).reply(400, { error: 'access_denied' });
    const provider = new CibaProvider({ clientId: 'cid', loginHint: 'user@example.com' });
    await expect(makeClient(provider).getCredential()).rejects.toBeInstanceOf(ApprovalDenied);
  });

  it('raises ApprovalTimeout when expired', async () => {
    initiate().post(TOKEN_PATH).reply(400, { error: 'expired_token' });
    const provider = new CibaProvider({ clientId: 'cid', loginHint: 'user@example.com' });
    await expect(makeClient(provider).getCredential()).rejects.toBeInstanceOf(ApprovalTimeout);
  });
});

describe('ManagementKeyProvider', () => {
  it('requires explicit opt-in', () => {
    expect(() => new ManagementKeyProvider({ managementKey: 'K123' })).toThrow(
      CredentialAcquisitionFailed,
    );
  });

  it('is privileged when opted in', async () => {
    const provider = new ManagementKeyProvider({
      managementKey: 'K123',
      allowManagementKey: true,
      logger: { debug: () => {}, warn: () => {} },
    });
    const client = makeClient(provider);
    const cred = await client.getCredential();
    expect(cred.token).toBe('K123');
    expect(client.credential.isPrivileged).toBe(true);
  });
});

describe('JwtBearerProvider', () => {
  it('exchanges a signed assertion for a credential', async () => {
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'jb_at', expires_in: 3600 });

    const client = makeClient(
      new JwtBearerProvider({ clientId: 'cid', assertion: 'signed.jwt.here', scopes: ['openid'] }),
    );
    const cred = await client.getCredential();

    expect(cred.token).toBe('jb_at');
    expect(body.grant_type).toBe('urn:ietf:params:oauth:grant-type:jwt-bearer');
    expect(body.assertion).toBe('signed.jwt.here');
    expect(body.client_id).toBe('cid');
  });

  it('resolves an async assertion function each acquisition', async () => {
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'jb_at', expires_in: 3600 });

    const client = makeClient(
      new JwtBearerProvider({ clientId: 'cid', assertion: async () => 'fresh.jwt' }),
    );
    await client.getCredential();

    expect(body.assertion).toBe('fresh.jwt');
  });

  it('throws CredentialAcquisitionFailed on a bad assertion', async () => {
    nock(BASE_URL).post(TOKEN_PATH).reply(400, { error: 'invalid_grant' });
    const client = makeClient(new JwtBearerProvider({ clientId: 'cid', assertion: 'bad' }));
    await expect(client.getCredential()).rejects.toBeInstanceOf(CredentialAcquisitionFailed);
  });
});
