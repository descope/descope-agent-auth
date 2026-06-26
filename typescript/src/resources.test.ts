import nock from 'nock';
import { BASE_URL, makeClient } from './testutils';
import { ClientCredentialsProvider, ManagementKeyProvider } from './providers';
import { AgentAuthError, PolicyDenied } from './errors';

const TOKEN_PATH = '/oauth2/v1/token';
const silentLogger = { debug: () => {}, warn: () => {} };

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

// Registers the phase-1 acquisition interceptor (first POST to the token endpoint)
// and returns the client. Register the token-exchange interceptor AFTER calling
// this so nock matches them in request order.
const agentClient = () => {
  nock(BASE_URL).post(TOKEN_PATH).reply(200, { access_token: 'agent_at', expires_in: 3600 });
  return makeClient(new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }));
};

describe('ResourcesClient.getToken (token-exchange)', () => {
  it('mints a Resource token via the token-exchange grant', async () => {
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
    expect(body.grant_type).toBe('urn:ietf:params:oauth:grant-type:token-exchange');
    expect(body.resource).toBe('urn:my-api');
    expect(body.subject_token).toBe('agent_at');
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
