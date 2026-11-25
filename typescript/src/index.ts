/**
 * @descope/agent-auth: acquire a Descope credential for an agent, then exchange
 * it for Connection / Resource tokens from the Descope vault. Two phases, nothing
 * more.
 */

export type { AgentAuthClientOptions } from './client';
export { AgentAuthClient } from './client';
// errors
export {
  AgentAuthError,
  ApprovalDenied,
  ApprovalTimeout,
  ConnectionAuthorizationRequired,
  ConnectUrlFailed,
  CredentialAcquisitionFailed,
  InvalidAuthorizationDetails,
  PolicyDenied,
  TokenExchangeFailed,
} from './errors';
export type { ToolRequest } from './execution';
// execution seam
export { Execution } from './execution';
// http config types
export type { Logger, RetryConfig } from './httpClient';
export type { InterruptFn, LangGraphConnectionOptions } from './integrations/langgraph';
// integrations (optional, framework-specific)
export { interruptPayload, langgraphConnectionTool } from './integrations/langgraph';
export type {
  McpAuthProvider,
  McpConnectionAuthOptions,
  McpOAuthTokens,
  McpResourceAuthOptions,
} from './integrations/mcp';
export {
  descopeMcpConnectionAuthProvider,
  descopeMcpResourceAuthProvider,
} from './integrations/mcp';
export type {
  AccessTokenOptions,
  CibaAuthenticateArgs,
  CibaOptions,
  ClientCredentialsOptions,
  DeviceCodeOptions,
  JwtBearerOptions,
  ManagementKeyOptions,
} from './providers';
// providers
export {
  AccessTokenProvider,
  CibaProvider,
  ClientCredentialsProvider,
  CredentialProvider,
  DeviceCodeProvider,
  JwtBearerProvider,
  ManagementKeyProvider,
} from './providers';
export type { TokenStore } from './store';
// store
export { MemoryTokenStore } from './store';
export type { ToolFn, WithConnectionOptions } from './tools';
// tools
export { withConnection } from './tools';

// types
export type {
  ApprovalRequest,
  Credential,
  CredentialKind,
  Mode,
  PendingAuthorization,
  VaultToken,
} from './types';
// vault arg types
export type { GetConnectionTokenArgs, GetResourceTokenArgs } from './vault';
export type {
  ExecuteConnectionArgs,
  GetConnectUrlArgs,
  GetTenantConnectionTokenArgs,
  WaitForConnectionArgs,
} from './vault/connections';
