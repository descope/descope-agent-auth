// Every request identifies the SDK, like Descope's node-sdk and core-js-sdk do.
// Descope analytics groups traffic by x-descope-sdk-name + x-descope-sdk-version, so
// this SDK uses its own name rather than `nodejs` (the core node-sdk).
import nock from 'nock';
import pkg from '../package.json';
import { ClientCredentialsProvider } from './providers';
import { BASE_URL, makeClient } from './testutils';
import { SDK_VERSION } from './version';

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

describe('SDK identification headers', () => {
  it('sends x-descope-sdk-* headers on every Descope request', async () => {
    let headers: Record<string, unknown> = {};
    nock(BASE_URL)
      .post(/.*/)
      .reply(function reply() {
        headers = this.req.headers;
        return [200, { access_token: 'agent_at', expires_in: 3600 }];
      });

    await makeClient(
      new ClientCredentialsProvider({ clientId: 'cid', clientSecret: 's' }),
    ).getCredential();

    expect(headers['x-descope-sdk-name']).toBe('agent-auth-js');
    expect(headers['x-descope-sdk-version']).toBe(pkg.version);
    expect(headers['x-descope-sdk-node-version']).toBe(process.versions.node);
  });

  it('keeps SDK_VERSION in sync with package.json', () => {
    expect(SDK_VERSION).toBe(pkg.version);
  });
});
