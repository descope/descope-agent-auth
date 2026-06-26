import nock from 'nock';
import { BASE_URL, makeClient, tokenObj } from './testutils';
import { ManagementKeyProvider } from './providers';

const TENANT_LATEST = '/v1/mgmt/outbound/app/tenant/token/latest';
const TENANT_SCOPED = '/v1/mgmt/outbound/app/tenant/token';
const silentLogger = { debug: () => {}, warn: () => {} };

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

const client = () =>
  makeClient(
    new ManagementKeyProvider({
      managementKey: 'K',
      allowManagementKey: true,
      logger: silentLogger,
    }),
  );

describe('ResourcesClient.getToken', () => {
  it('omitted scopes -> tenant /latest', async () => {
    nock(BASE_URL)
      .post(TENANT_LATEST)
      .reply(200, { token: tokenObj({ appId: 'urn:res', scopes: ['read'] }) });
    const tok = await client().resources.getToken({ resource: 'urn:res' });
    expect(tok.accessToken).toBe('gho_downstream_token');
    expect(tok.scopes).toEqual(['read']);
  });

  it('explicit scopes -> tenant scoped endpoint', async () => {
    let body: any;
    nock(BASE_URL)
      .post(TENANT_SCOPED, (b) => {
        body = b;
        return true;
      })
      .reply(200, { token: tokenObj({ appId: 'urn:res', scopes: ['read', 'write'] }) });
    const tok = await client().resources.getToken({
      resource: 'urn:res',
      scopes: ['read', 'write'],
      tenantId: 't1',
    });
    expect(tok.scopes).toEqual(['read', 'write']);
    expect(body.scopes).toEqual(['read', 'write']);
    expect(body.tenantId).toBe('t1');
  });
});
