import nock from 'nock';
import { BASE_URL, makeClient } from './testutils';
import { AuthorizationCodeProvider } from './providers';
import { CredentialAcquisitionFailed } from './errors';

const TOKEN_PATH = '/oauth2/v1/token';

beforeAll(() => nock.disableNetConnect());
afterEach(() => nock.cleanAll());
afterAll(() => nock.enableNetConnect());

describe('AuthorizationCodeProvider', () => {
  it('builds an authorize URL with PKCE params', async () => {
    const provider = new AuthorizationCodeProvider({
      clientId: 'cid',
      redirectUri: 'https://app/cb',
      scopes: ['openid', 'email'],
      baseUrlForAuthorize: BASE_URL,
    });
    const url = await provider.buildAuthorizeUrl('xyz');
    expect(url).toContain(`${BASE_URL}/oauth2/v1/authorize?`);
    expect(url).toContain('client_id=cid');
    expect(url).toContain('code_challenge=');
    expect(url).toContain('code_challenge_method=S256');
    expect(url).toContain('state=xyz');
    expect(url).toContain('scope=openid+email');
  });

  it('fails clearly when no authorization code is available', async () => {
    const provider = new AuthorizationCodeProvider({
      clientId: 'cid',
      redirectUri: 'https://app/cb',
    });
    await expect(makeClient(provider).getCredential()).rejects.toBeInstanceOf(
      CredentialAcquisitionFailed,
    );
  });

  it('completes with a captured code', async () => {
    nock(BASE_URL).post(TOKEN_PATH).reply(200, { access_token: 'authz_at', expires_in: 3600 });
    const provider = new AuthorizationCodeProvider({
      clientId: 'cid',
      redirectUri: 'https://app/cb',
      codeVerifier: 'v',
    });
    makeClient(provider);
    const cred = await provider.complete('the-code');
    expect(cred.token).toBe('authz_at');
  });
});
