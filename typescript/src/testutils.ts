/* eslint-disable import/no-extraneous-dependencies */
import { AgentAuthClient, AgentAuthClientOptions } from './client';
import { CredentialProvider } from './providers/base';

export const BASE_URL = 'https://api.descope.com';
export const PROJECT_ID = 'P2test';

export const makeClient = (
  credential: CredentialProvider,
  opts: Partial<Omit<AgentAuthClientOptions, 'projectId' | 'baseUrl' | 'credential'>> = {},
): AgentAuthClient =>
  new AgentAuthClient({ projectId: PROJECT_ID, baseUrl: BASE_URL, credential, ...opts });

export const tokenObj = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'tok_1',
  appId: 'github',
  userId: 'user@example.com',
  accessToken: 'gho_downstream_token',
  accessTokenType: 'Bearer',
  accessTokenExpiry: String(Math.floor(Date.now() / 1000) + 3600),
  hasRefreshToken: false,
  scopes: ['repo'],
  ...overrides,
});
