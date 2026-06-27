// Tiny shared helper for the example scripts: read env vars, fail loudly.

export function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    console.error(`Missing required env var: ${name}  (see examples/.env.example)`);
    process.exit(1);
  }
  return value;
}

export const optional = (name: string, fallback: string): string => process.env[name] || fallback;

export const baseUrl = (): string => optional('DESCOPE_BASE_URL', 'https://api.descope.com');

// Show enough of a token to confirm you got one, without dumping the secret.
export const preview = (token: string): string =>
  token.length > 16 ? `${token.slice(0, 8)}…${token.slice(-4)}` : '<short>';
