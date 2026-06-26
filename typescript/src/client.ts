/**
 * AgentAuthClient -- the main entry point.
 *
 * Configured once with the project, the Descope base URL, and a credential
 * provider that encodes the phase-1 strategy. Thereafter call phase-2 exchange
 * (`client.connections.getToken` / `client.resources.getToken`) repeatedly
 * without thinking about the bootstrap again; refresh happens transparently.
 */

import { AgentAuthError } from './errors';
import { Execution } from './execution';
import { HttpClient, Logger, RetryConfig } from './httpClient';
import { CibaProvider } from './providers/ciba';
import { CredentialProvider } from './providers/base';
import { MemoryTokenStore } from './store/memory';
import { TokenStore } from './store/base';
import { ApprovalRequest, Credential, Mode } from './types';
import { VaultBackend } from './vault/base';
import { ConnectionsClient } from './vault/connections';
import { ResourcesClient } from './vault/resources';

export interface AgentAuthClientOptions {
  projectId: string;
  credential: CredentialProvider;
  baseUrl?: string;
  store?: TokenStore;
  mode?: Mode;
  /** Optional CIBA provider used to gate sensitive exchanges (requireApproval). */
  approval?: CibaProvider;
  timeoutMs?: number;
  retry?: RetryConfig;
  logger?: Logger;
}

export class AgentAuthClient {
  readonly projectId: string;

  readonly baseUrl: string;

  readonly mode: Mode;

  readonly store: TokenStore;

  readonly credential: CredentialProvider;

  readonly connections: ConnectionsClient;

  readonly resources: ResourcesClient;

  private readonly http: HttpClient;

  private readonly approval?: CibaProvider;

  constructor(opts: AgentAuthClientOptions) {
    this.projectId = opts.projectId;
    this.baseUrl = opts.baseUrl ?? 'https://api.descope.com';
    this.mode = opts.mode ?? 'fetch';
    this.store = opts.store ?? new MemoryTokenStore();

    const { logger } = opts;
    this.http = new HttpClient({
      baseUrl: this.baseUrl,
      timeoutMs: opts.timeoutMs,
      retry: opts.retry,
      logger,
    });

    // Phase 1: bind the provider so it can talk to Descope and persist its
    // credential (incl. refresh token) to the token store.
    this.credential = opts.credential;
    this.credential.bind(this.http, this.projectId, this.store);
    if (this.credential.isPrivileged) {
      (logger ?? { warn: () => {}, debug: () => {} }).warn(
        'AgentAuthClient configured with a privileged (management-key) credential: ' +
          'vault exchanges will BYPASS Policies.',
      );
    }

    // Optional phase-2 approval gate: a CIBA provider used to require a fresh user
    // sign-off before a sensitive exchange (see requireApproval).
    this.approval = opts.approval;
    if (this.approval) {
      this.approval.bind(this.http, this.projectId, this.store);
    }

    const backend = new VaultBackend(
      this.http,
      this.projectId,
      () => this.getCredential(),
      this.store,
      (request) => this.runApproval(request),
    );
    // The execution seam wraps the backend: fetch is wired, execute is stubbed
    // behind the mode flag so enabling it later is a config change, not a rewrite.
    const execution = new Execution(this.mode, backend);
    this.connections = new ConnectionsClient(execution);
    // Connection tokens come from the vault (via the execution seam); Resource
    // tokens are minted by the token-exchange grant directly off the phase-1
    // credential, so ResourcesClient is wired to the HTTP + credential layer.
    this.resources = new ResourcesClient({
      http: this.http,
      getCredential: () => this.getCredential(),
      store: this.store,
      mode: this.mode,
      approvalGate: (request) => this.runApproval(request),
    });
  }

  private async runApproval(request: ApprovalRequest): Promise<void> {
    if (!this.approval) {
      throw new AgentAuthError(
        'requireApproval was set but no approval provider is configured on the client; ' +
          'pass approval: new CibaProvider(...) to AgentAuthClient',
      );
    }
    await this.approval.authenticate({
      loginHint: request.loginHint,
      bindingMessage: request.bindingMessage,
      scopes: request.scopes,
      timeoutSeconds: request.timeoutSeconds,
    });
  }

  /** Return the current phase-1 Descope credential, refreshing if needed. */
  getCredential(): Promise<Credential> {
    return this.credential.getCredential();
  }

  refreshCredential(): Promise<Credential> {
    return this.credential.refresh();
  }
}
