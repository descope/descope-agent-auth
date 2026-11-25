import nock from 'nock';
import { BASE_URL, makeClient } from './testutils';
import {
  AccessTokenProvider,
  CibaProvider,
  ClientCredentialsProvider,
  ManagementKeyProvider,
} from './providers';
import {
  AgentAuthError,
  CredentialAcquisitionFailed,
  PolicyDenied,
  TokenExchangeFailed,
} from './errors';
import { MemoryTokenStore } from './store';
import { Credential } from './types';

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

  clientAuth(): Record<string, string> {
    return { client_id: 'cid', client_secret: 's' };
  }
}

// A user-bound provider with a stable identity (like CibaProvider). Each
// credential resolution yields a rotated token, and the calls are counted.
class IdentifiedUserProvider extends UserBoundProvider {
  credentialCalls = 0;

  constructor(
    private readonly user: string,
    private readonly identity: string,
  ) {
    super(`${user}_jwt`);
  }

  identityKey(): string {
    return this.identity;
  }

  async getCredential(): Promise<Credential> {
    this.credentialCalls += 1;
    return { token: `${this.user}_jwt_${this.credentialCalls}`, kind: 'agent_token' };
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

  // Every Resource request carries the client secret, so go by the OAuth error, not
  // the HTTP status. Legacy envelope (strict OAuth errors off) too.
  it.each<[number, Record<string, unknown>, Function]>([
    [401, { error: 'invalid_client' }, CredentialAcquisitionFailed],
    [
      400,
      {
        errorCode: 'E074130',
        errorDescription: 'invalid_client',
        errorMessage: 'Invalid client id',
      },
      CredentialAcquisitionFailed,
    ],
    [400, { error: 'unauthorized_client' }, PolicyDenied],
    [400, { error: 'invalid_target' }, PolicyDenied],
    [403, { error: 'access_denied' }, PolicyDenied],
    [
      400,
      { error: 'invalid_scope', error_description: 'Requested scope not granted' },
      PolicyDenied,
    ],
    [
      400,
      {
        errorCode: 'E063313',
        errorDescription: 'unauthorized_client',
        errorMessage: 'Client is not authorized',
      },
      PolicyDenied,
    ],
    [400, { errorCode: 'E063309', errorMessage: 'Scope not allowed' }, PolicyDenied],
    [403, { message: 'forbidden' }, PolicyDenied],
    [400, { error: 'invalid_request' }, TokenExchangeFailed],
    [401, { error: 'invalid_token' }, TokenExchangeFailed],
  ])('maps %i %j to the matching error', async (status, body, expected) => {
    const client = agentClient();
    nock(BASE_URL).post(TOKEN_PATH).reply(status, body);
    const err = await client.resources.getToken({ resource: 'urn:my-api' }).catch((e) => e);
    expect(err.constructor).toBe(expected);
  });

  it('serves a cached token for an identified provider before resolving its credential', async () => {
    // A provider with a stable identity (CIBA) keys the cache by that identity, so
    // a cached Resource token never triggers a refresh or a new approval, and the
    // entry survives the phase-1 credential's rotation.
    const provider = new IdentifiedUserProvider('alice', 'cred:ciba:P:cid:alice');
    const client = makeClient(provider);
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .once()
      .reply(200, { access_token: 'alice_resource_at', expires_in: 3600 });

    const first = await client.resources.getToken({ resource: 'urn:my-api' });
    const again = await client.resources.getToken({ resource: 'urn:my-api' });

    expect(first.accessToken).toBe('alice_resource_at');
    expect(again.accessToken).toBe('alice_resource_at');
    expect(provider.credentialCalls).toBe(1); // only on the cache miss
    expect(body.subject_token).toBe('alice_jwt_1');
  });

  it('keys identified providers per identity on a shared store', async () => {
    const minted = ['alice_resource_at', 'bob_resource_at'];
    nock(BASE_URL)
      .post(TOKEN_PATH)
      .times(2)
      .reply(() => [200, { access_token: minted.shift(), expires_in: 3600 }]);
    const store = new MemoryTokenStore();
    const alice = makeClient(new IdentifiedUserProvider('alice', 'id:alice'), { store });
    const bob = makeClient(new IdentifiedUserProvider('bob', 'id:bob'), { store });

    expect((await alice.resources.getToken({ resource: 'urn:my-api' })).accessToken).toBe(
      'alice_resource_at',
    );
    expect((await bob.resources.getToken({ resource: 'urn:my-api' })).accessToken).toBe(
      'bob_resource_at',
    );
  });

  it('gives each CIBA user its own identity', () => {
    const alice = new CibaProvider({ clientId: 'cid', clientSecret: 's', loginHint: 'a@x.com' });
    const bob = new CibaProvider({ clientId: 'cid', clientSecret: 's', loginHint: 'b@x.com' });
    makeClient(alice);
    makeClient(bob);
    expect(alice.identityKey()).toBeDefined();
    expect(alice.identityKey()).not.toBe(bob.identityKey());
    // Providers without one stable subject key by the credential instead.
    expect(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }).identityKey(),
    ).toBeUndefined();
    expect(new AccessTokenProvider({ accessToken: 't' }).identityKey()).toBeUndefined();
  });
});
