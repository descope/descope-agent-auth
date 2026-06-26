import nock from 'nock';
import { BASE_URL, PROJECT_ID, makeClient, tokenObj } from './testutils';
import { AccessTokenProvider, ClientCredentialsProvider } from './providers';

const USER_LATEST = '/v1/mgmt/outbound/app/user/token/latest';
const TOKEN_PATH = '/oauth2/v1/token';

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

describe('AccessTokenProvider (bring-your-own user token)', () => {
  it('uses the supplied token without acquiring one', async () => {
    const client = makeClient(new AccessTokenProvider({ accessToken: 'user_jwt' }));
    const cred = await client.getCredential();
    expect(cred.token).toBe('user_jwt');
    expect(client.credential.isPrivileged).toBe(false);
  });

  it('makes the connection fetch user-scoped', async () => {
    let auth: string | undefined;
    nock(BASE_URL)
      .post(USER_LATEST)
      .reply(function reply() {
        auth = this.req.headers.authorization as string;
        return [200, { token: tokenObj() }];
      });

    await makeClient(new AccessTokenProvider({ accessToken: 'user_jwt' })).connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
    });

    expect(auth).toBe(`Bearer ${PROJECT_ID}:user_jwt`);
  });

  it('uses the user token as the token-exchange subject for resources', async () => {
    let body: any;
    nock(BASE_URL)
      .post(TOKEN_PATH, (b) => {
        body = b;
        return true;
      })
      .reply(200, { access_token: 'resource_at', expires_in: 3600, scope: 'read' });

    const tok = await makeClient(
      new AccessTokenProvider({ accessToken: 'user_jwt' }),
    ).resources.getToken({ resource: 'urn:my-api', scopes: ['read'] });

    expect(tok.accessToken).toBe('resource_at');
    expect(body.subject_token).toBe('user_jwt');
  });
});

describe('actAsUserToken per-call override (one shared client, many users)', () => {
  // Register the phase-1 acquisition interceptor and return the autonomous client.
  const agentClient = () => {
    nock(BASE_URL).post(TOKEN_PATH).reply(200, { access_token: 'agent_at', expires_in: 3600 });
    return makeClient(new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }));
  };

  it('overrides the bearer with the user token (no phase-1 call needed)', async () => {
    let auth: string | undefined;
    // The override supplies the credential, so no acquisition happens: a single call.
    nock(BASE_URL)
      .post(USER_LATEST)
      .reply(function reply() {
        auth = this.req.headers.authorization as string;
        return [200, { token: tokenObj() }];
      });

    await makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    ).connections.getToken({
      connection: 'github',
      identifier: 'user@example.com',
      actAsUserToken: 'user_jwt',
    });

    expect(auth).toBe(`Bearer ${PROJECT_ID}:user_jwt`);
  });

  it('sets the user token as the resources subject_token', async () => {
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
  });

  it('without the override, uses the client credential as bearer', async () => {
    let auth: string | undefined;
    const client = agentClient();
    nock(BASE_URL)
      .post(USER_LATEST)
      .reply(function reply() {
        auth = this.req.headers.authorization as string;
        return [200, { token: tokenObj() }];
      });

    await client.connections.getToken({ connection: 'github', identifier: 'user@example.com' });

    expect(auth).toBe(`Bearer ${PROJECT_ID}:agent_at`);
  });
});
