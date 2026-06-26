/**
 * Pluggable token cache interface.
 *
 * A `TokenStore` caches both the phase-1 Descope credential and the phase-2
 * downstream tokens. It is a dumb key/value cache with a TTL hint, so it can be
 * backed by memory, Redis, a database, or a secrets manager without changing the
 * SDK. Implementations MUST NOT log stored values.
 */

export interface TokenStore {
  /** Return the stored value, or `undefined` if absent/expired. */
  get(key: string): Promise<string | undefined> | string | undefined;
  /** Store `value` under `key`. `ttlSeconds` is an optional expiry hint. */
  set(key: string, value: string, ttlSeconds?: number): Promise<void> | void;
  /** Remove `key` if present (no error if absent). */
  delete(key: string): Promise<void> | void;
  /** Return the currently-stored (non-expired) keys. */
  list(): Promise<string[]> | string[];
}
