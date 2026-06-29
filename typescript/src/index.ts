/**
 * @descope/agent-auth: acquire a Descope credential for an agent, then exchange
 * it for Connection / Resource tokens from the Descope vault. Two phases, nothing
 * more.
 */

export { AgentAuthClient } from './client';
export type { AgentAuthClientOptions } from './client';

// providers
export {
  CredentialProvider,
  AccessTokenProvider,
  ClientCredentialsProvider,
  DeviceCodeProvider,
  CibaProvider,
  JwtBearerProvider,
  ManagementKeyProvider,
} from './providers';
export type {
  AccessTokenOptions,
  ClientCredentialsOptions,
  DeviceCodeOptions,
  CibaOptions,
  CibaAuthenticateArgs,
  JwtBearerOptions,
  ManagementKeyOptions,
} from './providers';

// store
export { MemoryTokenStore } from './store';
export type { TokenStore } from './store';

// tools
export { withConnection } from './tools';
export type { WithConnectionOptions, ToolFn } from './tools';

// integrations (optional, framework-specific)
export { langgraphConnectionTool, interruptPayload } from './integrations/langgraph';
export type { LangGraphConnectionOptions, InterruptFn } from './integrations/langgraph';
export {
  descopeMcpConnectionAuthProvider,
  descopeMcpResourceAuthProvider,
} from './integrations/mcp';
export type {
  McpAuthProvider,
  McpOAuthTokens,
  McpConnectionAuthOptions,
  McpResourceAuthOptions,
} from './integrations/mcp';

// execution seam
export { Execution } from './execution';
export type { ToolRequest } from './execution';

// vault arg types
export type { GetConnectionTokenArgs, GetResourceTokenArgs } from './vault';
export type {
  ExecuteConnectionArgs,
  GetTenantConnectionTokenArgs,
  GetConnectUrlArgs,
  WaitForConnectionArgs,
} from './vault/connections';

// types
export type {
  Credential,
  CredentialKind,
  Mode,
  PendingAuthorization,
  ApprovalRequest,
  VaultToken,
} from './types';

// errors
export {
  AgentAuthError,
  ConnectionAuthorizationRequired,
  PolicyDenied,
  CredentialAcquisitionFailed,
  TokenExchangeFailed,
  ApprovalDenied,
  ApprovalTimeout,
} from './errors';

// http config types
export type { RetryConfig, Logger } from './httpClient';
