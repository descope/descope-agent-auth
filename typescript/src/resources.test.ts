import nock from 'nock';
import { BASE_URL, makeClient } from './testutils';
import { AccessTokenProvider, ClientCredentialsProvider, ManagementKeyProvider } from './providers';
import { AgentAuthError, PolicyDenied } from './errors';
import { MemoryTokenStore } from './store';

// Agent client_credentials and token-exchange are both served by the inbound-apps server.
const TOKEN_PATH = '/oauth2/v1/apps/token';
const silentLogger = { debug: () => {}, warn: () => {} };

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

const agentClient = () =>
  makeClient(new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }));

// A user's token plus a confidential client, like a CibaProvider with a secret.
class UserBoundProvider extends AccessTokenProvider {
  constructor(userJwt: string) {
    super({ accessToken: userJwt });
  }

  tokenExchangeClientAuth(): Record<string, string> {
    return { client_id: 'cid', client_secret: 's' };
  }
}

describe('ResourcesClient.getToken', () => {
  it('requests the agent’s own token with client_credentials and the resource', async () => {
    // Descope applies client-access Policies only to a client_credentials request
    // that names the resource; a self token-exchange is refused.
    const client = agentClient();
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, {
        access_token: 'resource_at',
        token_type: 'Bearer',
        expires_in: 3600,
        scope: 'read',
      });

    const tok = await client.resources.getToken({ resource: 'urn:my-api', scopes: ['read'] });

    expect(tok.accessToken).toBe('resource_at');
    expect(tok.scopes).toEqual(['read']);
    expect(body.grant_type).toBe('client_credentials');
    expect(body.resource).toBe('urn:my-api');
    expect(body.scope).toBe('read');
    expect(body.client_id).toBe('cid');
    expect(body.client_secret).toBe('s');
    expect(body.subject_token).toBeUndefined();
  });

  it('authenticates the agent client on a user-scoped exchange', async () => {
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'resource_at', expires_in: 3600 });

    await makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    ).resources.getToken({ resource: 'urn:my-api', actAsUserToken: 'user_jwt' });

    expect(body.subject_token).toBe('user_jwt');
    expect(body.client_id).toBe('cid');
    expect(body.client_secret).toBe('s');
  });

  it('never serves one user’s token to another user (or the agent) from cache', async () => {
    const minted: string[] = ['alice_resource_at', 'bob_resource_at', 'agent_res_at'];
    const scope = nock(BASE_URL)
      .post(TOKEN_PATH)
      .times(minted.length)
      .reply(() => [200, { access_token: minted.shift(), expires_in: 3600 }]);
    const client = makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    );

    const alice = await client.resources.getToken({
      resource: 'urn:my-api',
      actAsUserToken: 'alice_jwt',
    });
    const bob = await client.resources.getToken({
      resource: 'urn:my-api',
      actAsUserToken: 'bob_jwt',
    });
    const aliceAgain = await client.resources.getToken({
      resource: 'urn:my-api',
      actAsUserToken: 'alice_jwt',
    });
    const own = await client.resources.getToken({ resource: 'urn:my-api' });

    expect(alice.accessToken).toBe('alice_resource_at');
    expect(bob.accessToken).toBe('bob_resource_at');
    expect(aliceAgain.accessToken).toBe('alice_resource_at'); // cached per user
    expect(own.accessToken).toBe('agent_res_at');
    expect(scope.isDone()).toBe(true);
  });

  it('never mixes two agent clients on a shared store (same user)', async () => {
    const bodies: any[] = [];
    const minted = ['a_resource_at', 'b_resource_at'];
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        bodies.push(b);
        return true;
      })
      .times(2)
      .reply(() => [200, { access_token: minted.shift(), expires_in: 3600 }]);
    const store = new MemoryTokenStore();
    const a = makeClient(new ClientCredentialsProvider({ clientId: 'a', clientSecret: 's' }), {
      store,
    });
    const b = makeClient(new ClientCredentialsProvider({ clientId: 'b', clientSecret: 's' }), {
      store,
    });

    const tokA = await a.resources.getToken({
      resource: 'urn:my-api',
      actAsUserToken: 'alice_jwt',
    });
    const tokB = await b.resources.getToken({
      resource: 'urn:my-api',
      actAsUserToken: 'alice_jwt',
    });

    expect(tokA.accessToken).toBe('a_resource_at');
    expect(tokB.accessToken).toBe('b_resource_at');
    expect(bodies[1].client_id).toBe('b');
  });

  it('never mixes two agent clients’ own tokens on a shared store', async () => {
    const minted = ['a_resource_at', 'b_resource_at'];
    const scope = nock(BASE_URL)
      .post(TOKEN_PATH)
      .times(minted.length)
      .reply(() => [200, { access_token: minted.shift(), expires_in: 3600 }]);
    const store = new MemoryTokenStore();
    const a = makeClient(new ClientCredentialsProvider({ clientId: 'a', clientSecret: 's' }), {
      store,
    });
    const b = makeClient(new ClientCredentialsProvider({ clientId: 'b', clientSecret: 's' }), {
      store,
    });

    const tokA = await a.resources.getToken({ resource: 'urn:my-api' });
    const tokB = await b.resources.getToken({ resource: 'urn:my-api' });
    const tokAAgain = await a.resources.getToken({ resource: 'urn:my-api' });

    expect(tokA.accessToken).toBe('a_resource_at');
    expect(tokB.accessToken).toBe('b_resource_at');
    expect(tokAAgain.accessToken).toBe('a_resource_at'); // still cached
    expect(scope.isDone()).toBe(true);
  });

  it('sends the audience claim (repeated params) on the token exchange', async () => {
    const client = agentClient();
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'resource_at', token_type: 'Bearer' });

    await client.resources.getToken({
      resource: 'urn:my-api',
      audience: ['https://api.acme.com', 'https://api2.acme.com'],
      actAsUserToken: 'user_jwt',
    });

    expect(body.audience).toEqual(['https://api.acme.com', 'https://api2.acme.com']);
  });

  it('exchanges a user-bound credential and keys it per user on a shared store', async () => {
    const bodies: any[] = [];
    const minted = ['alice_resource_at', 'bob_resource_at'];
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        bodies.push(b);
        return true;
      })
      .times(2)
      .reply(() => [200, { access_token: minted.shift(), expires_in: 3600 }]);
    const store = new MemoryTokenStore();
    const alice = makeClient(new UserBoundProvider('alice_jwt'), { store });
    const bob = makeClient(new UserBoundProvider('bob_jwt'), { store });

    const tokAlice = await alice.resources.getToken({ resource: 'urn:my-api' });
    const tokBob = await bob.resources.getToken({ resource: 'urn:my-api' });

    expect(tokAlice.accessToken).toBe('alice_resource_at');
    expect(tokBob.accessToken).toBe('bob_resource_at');
    expect(bodies[1].grant_type).toBe('urn:ietf:params:oauth:grant-type:token-exchange');
    expect(bodies[1].subject_token).toBe('bob_jwt');
    expect(bodies[1].client_id).toBe('cid');
  });

  it('rejects a Management Key (token-exchange needs an OAuth identity)', async () => {
    const client = makeClient(
      new ManagementKeyProvider({
        managementKey: 'K',
        allowManagementKey: true,
        logger: silentLogger,
      }),
    );
    await expect(client.resources.getToken({ resource: 'urn:my-api' })).rejects.toBeInstanceOf(
      AgentAuthError,
    );
  });

  it('maps 403 to PolicyDenied', async () => {
    const client = agentClient();
    nock(BASE_URL).post(TOKEN_PATH).reply(403, { error: 'access_denied' });
    await expect(client.resources.getToken({ resource: 'urn:my-api' })).rejects.toBeInstanceOf(
      PolicyDenied,
    );
  });
});
