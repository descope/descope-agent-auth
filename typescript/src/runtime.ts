/**
 * Cross-runtime crypto/encoding helpers.
 *
 * The SDK must run on any JavaScript runtime an agent might live in -- Node,
 * Cloudflare Workers, Deno, Bun, and browsers. That rules out `node:crypto` and
 * `Buffer`, which aren't present (or aren't default) on edge runtimes. Everything
 * here is built on the universal Web primitives (`globalThis.crypto`, `btoa`,
 * `TextEncoder`), with a lazy Node WebCrypto fallback that is only ever reached on
 * older Node versions -- never on an edge runtime, where `globalThis.crypto` is
 * always present.
 */

const textEncoder = new TextEncoder();

function bytesToBase64(bytes: Uint8Array): string {
  let bin = '';
  for (let i = 0; i < bytes.length; i += 1) {
    bin += String.fromCharCode(bytes[i]);
  }
  if (typeof btoa === 'function') return btoa(bin);
  // Fallback for runtimes without btoa (older Node); Buffer is global there.
  return Buffer.from(bin, 'binary').toString('base64');
}

function toBase64Url(bytes: Uint8Array): string {
  return bytesToBase64(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Base64 of a UTF-8 string (used for HTTP Basic auth). */
export function base64(input: string): string {
  return bytesToBase64(textEncoder.encode(input));
}

async function webCrypto(): Promise<Crypto> {
  const g = (globalThis as { crypto?: Crypto }).crypto;
  if (g && g.subtle) return g;
  // Only reached on Node versions without a global WebCrypto; never on edge.
  const nodeCrypto = (await import('node:crypto')) as unknown as { webcrypto: Crypto };
  return nodeCrypto.webcrypto;
}

/** A URL-safe random token (used as a PKCE code_verifier). */
export async function randomUrlToken(byteLength = 32): Promise<string> {
  const c = await webCrypto();
  const bytes = new Uint8Array(byteLength);
  c.getRandomValues(bytes);
  return toBase64Url(bytes);
}

/** The SHA-256 PKCE code_challenge for a given verifier. */
export async function sha256UrlChallenge(verifier: string): Promise<string> {
  const c = await webCrypto();
  const digest = await c.subtle.digest('SHA-256', textEncoder.encode(verifier));
  return toBase64Url(new Uint8Array(digest));
}
