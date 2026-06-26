/** In-memory token store: the default, fine for single-process agents. */

import { TokenStore } from './base';

interface Entry {
  value: string;
  expiresAt?: number;
}

export class MemoryTokenStore implements TokenStore {
  private data = new Map<string, Entry>();

  get(key: string): string | undefined {
    const entry = this.data.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt !== undefined && Date.now() >= entry.expiresAt) {
      this.data.delete(key);
      return undefined;
    }
    return entry.value;
  }

  set(key: string, value: string, ttlSeconds?: number): void {
    const expiresAt = ttlSeconds !== undefined ? Date.now() + ttlSeconds * 1000 : undefined;
    this.data.set(key, { value, expiresAt });
  }

  delete(key: string): void {
    this.data.delete(key);
  }

  list(): string[] {
    const keys: string[] = [];
    this.data.forEach((entry, key) => {
      if (entry.expiresAt !== undefined && Date.now() >= entry.expiresAt) {
        this.data.delete(key);
      } else {
        keys.push(key);
      }
    });
    return keys;
  }
}
