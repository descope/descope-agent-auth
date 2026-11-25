import { redact } from './httpClient';

const REDACTED = '***redacted***';

describe('redact (log masking)', () => {
  it('masks sensitive keys including the jwt-bearer assertion', () => {
    const masked = redact({
      assertion: 'signed.jwt',
      client_secret: 's',
      client_id: 'cid',
      scope: 'read',
    });
    expect(masked.assertion).toBe(REDACTED); // jwt-bearer credential
    expect(masked.client_secret).toBe(REDACTED);
    expect(masked.client_id).toBe('cid'); // not sensitive
    expect(masked.scope).toBe('read');
  });

  it('masks token-exchange tokens', () => {
    const masked = redact({
      subject_token: 'user.jwt',
      actor_token: 'agent.jwt',
      client_assertion: 'signed.jwt',
      subject_token_type: 'urn:ietf:params:oauth:token-type:access_token',
    });
    expect(masked.subject_token).toBe(REDACTED);
    expect(masked.actor_token).toBe(REDACTED);
    expect(masked.client_assertion).toBe(REDACTED);
    expect(masked.subject_token_type).toBe('urn:ietf:params:oauth:token-type:access_token');
  });

  it('masks authorization_details (transaction data)', () => {
    const masked = redact({ authorization_details: '[{"type":"payment_initiation"}]' });
    expect(masked.authorization_details).toBe(REDACTED);
  });

  it('masks nested values', () => {
    const masked = redact({ options: { assertion: 'x', prompt: 'consent' } }) as {
      options: Record<string, unknown>;
    };
    expect(masked.options.assertion).toBe(REDACTED);
    expect(masked.options.prompt).toBe('consent');
  });
});
