/**
 * ManagementKeyProvider -- privileged, NOT recommended.
 *
 * Wraps a static project Management Key. Not a flow; a high-privilege credential
 * that grants access to effectively everything in the vault and **bypasses
 * Policies**. Construction requires an explicit `allowManagementKey:
 * true` opt-in and emits a warning, to make the recommended-path guidance
 * unmissable.
 */

import { CredentialAcquisitionFailed } from '../errors';
import { Logger } from '../httpClient';
import { Credential } from '../types';
import { CredentialProvider } from './base';

export interface ManagementKeyOptions {
  managementKey: string;
  allowManagementKey?: boolean;
  logger?: Logger;
}

export class ManagementKeyProvider extends CredentialProvider {
  readonly kind = 'management_key';

  private readonly managementKey: string;

  constructor(opts: ManagementKeyOptions) {
    super();
    if (!opts.allowManagementKey) {
      throw new CredentialAcquisitionFailed(
        'ManagementKeyProvider bypasses Policies and grants broad vault ' +
          'access. It is not the recommended path. To proceed deliberately, pass ' +
          'allowManagementKey: true.',
      );
    }
    this.managementKey = opts.managementKey;
    // eslint-disable-next-line no-console
    const logger = opts.logger ?? { debug: () => {}, warn: console.warn.bind(console) };
    logger.warn(
      'ManagementKeyProvider in use: this credential BYPASSES Policies and ' +
        'grants broad vault access. Prefer an agent-token provider where possible.',
    );
  }

  protected async acquire(): Promise<Credential> {
    // A management key is static -- no acquisition or refresh needed.
    return { token: this.managementKey, kind: this.kind };
  }

  async refresh(): Promise<Credential> {
    return this.acquire();
  }
}
