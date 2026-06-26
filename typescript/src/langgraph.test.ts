import nock from 'nock';
import { BASE_URL, makeClient, tokenObj } from './testutils';
import { ManagementKeyProvider } from './providers';
import { langgraphConnectionTool, interruptPayload } from './integrations/langgraph';
import { ApprovalDenied, ConnectionAuthorizationRequired, PolicyDenied } from './errors';

const USER_SCOPED = '/v1/mgmt/outbound/app/user/token';
const CONNECT_PATH = '/v1/mgmt/outbound/app/connect';
const silentLogger = { debug: () => {}, warn: () => {} };

class Pause extends Error {} // stand-in for langgraph's GraphInterrupt

const mgmt = () =>
  new ManagementKeyProvider({ managementKey: 'K', allowManagementKey: true, logger: silentLogger });

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

describe('langgraphConnectionTool', () => {
  it('calls the tool without interrupting on the happy path', async () => {
    nock(BASE_URL).post(USER_SCOPED).reply(200, { token: tokenObj() });
    const events: unknown[] = [];

    const listRepos = langgraphConnectionTool(
      makeClient(mgmt()),
      { connection: 'github', scopes: ['repo'], interrupt: (v) => events.push(v) },
      async (token, identifier) => `${identifier}:${token}`,
    );

    expect(await listRepos('u@e.com')).toBe('u@e.com:gho_downstream_token');
    expect(events).toEqual([]);
  });

  it('interrupts (pauses) on connection-required with a connect-URL payload', async () => {
    nock(BASE_URL).post(USER_SCOPED).reply(404, { error: 'no' });
    nock(BASE_URL).post(CONNECT_PATH).reply(200, { url: 'https://api.descope.com/connect?x=1' });
    let captured: any;

    const listRepos = langgraphConnectionTool(
      makeClient(mgmt()),
      {
        connection: 'github',
        scopes: ['repo'],
        interrupt: (v) => {
          captured = v;
          throw new Pause(); // mimic GraphInterrupt
        },
      },
      async (token) => token,
    );

    await expect(listRepos('u@e.com')).rejects.toBeInstanceOf(Pause);
    expect(captured.type).toBe('connection_authorization_required');
    expect(captured.connectUrl).toBe('https://api.descope.com/connect?x=1');
  });

  it('retries the exchange after an inline resume', async () => {
    nock(BASE_URL).post(USER_SCOPED).reply(404, { error: 'no' });
    nock(BASE_URL).post(CONNECT_PATH).reply(200, { url: 'https://api.descope.com/connect' });
    nock(BASE_URL).post(USER_SCOPED).reply(200, { token: tokenObj() });
    let calls = 0;

    const listRepos = langgraphConnectionTool(
      makeClient(mgmt()),
      {
        connection: 'github',
        scopes: ['repo'],
        interrupt: () => {
          calls += 1;
          return 'resumed';
        },
      },
      async (token) => token,
    );

    expect(await listRepos('u@e.com')).toBe('gho_downstream_token');
    expect(calls).toBe(1);
  });

  it('propagates non-interrupt errors (e.g. PolicyDenied)', async () => {
    nock(BASE_URL).post(USER_SCOPED).reply(403, { error: 'policy denied' });

    const listRepos = langgraphConnectionTool(
      makeClient(mgmt()),
      { connection: 'github', scopes: ['repo'], interrupt: () => undefined },
      async (token) => token,
    );

    await expect(listRepos('u@e.com')).rejects.toBeInstanceOf(PolicyDenied);
  });

  it('builds payloads for each error type', () => {
    const car = new ConnectionAuthorizationRequired('x', {
      connectUrl: 'u',
      connection: 'github',
      identifier: 'i',
    });
    expect(interruptPayload(car).type).toBe('connection_authorization_required');
    expect(interruptPayload(new ApprovalDenied('d')).type).toBe('approval_denied');
  });
});
