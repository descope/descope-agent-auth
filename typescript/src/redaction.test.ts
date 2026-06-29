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

  it('masks nested values', () => {
    const masked = redact({ options: { assertion: 'x', prompt: 'consent' } }) as {
      options: Record<string, unknown>;
    };
    expect(masked.options.assertion).toBe(REDACTED);
    expect(masked.options.prompt).toBe('consent');
  });
});
