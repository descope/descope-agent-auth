/**
 * Thin HTTP layer over the global `fetch`.
 *
 * Responsibilities kept small: build absolute URLs from `baseUrl`, apply timeout
 * + bounded retry on transient failures, and never emit credential values in
 * logs. All higher layers (providers, vault) speak to Descope through one
 * `HttpClient` instance.
 */

import { AgentAuthError } from './errors';

const REDACTED = '***redacted***';
const SENSITIVE_KEYS = new Set([
  'authorization',
  'client_secret',
  'code',
  'code_verifier',
  'refresh_token',
  'access_token',
  'accesstoken',
  'refreshtoken',
  'token',
  'management_key',
  'device_code',
  'auth_req_id',
  'assertion',
]);

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

/** Return a copy of `data` with sensitive values masked, for logging. */
export const redact = (data?: Record<string, unknown> | null): Record<string, unknown> => {
  if (!data) return {};
  const out: Record<string, unknown> = {};
  Object.entries(data).forEach(([key, value]) => {
    if (SENSITIVE_KEYS.has(key.toLowerCase())) {
      out[key] = REDACTED;
    } else if (value && typeof value === 'object' && !Array.isArray(value)) {
      out[key] = redact(value as Record<string, unknown>);
    } else {
      out[key] = value;
    }
  });
  return out;
};

export interface Logger {
  debug: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
}

export interface RetryConfig {
  attempts: number;
  backoffMs: number;
  retryStatuses: number[];
}

export const DEFAULT_RETRY: RetryConfig = {
  attempts: 3,
  backoffMs: 250,
  retryStatuses: [429, 500, 502, 503, 504],
};

export interface HttpResponse {
  statusCode: number;
  ok: boolean;
  json: any;
  text: string;
}

type FetchImpl = typeof fetch;

export interface HttpClientOptions {
  baseUrl: string;
  timeoutMs?: number;
  retry?: RetryConfig;
  logger?: Logger;
  /** Injectable for tests; defaults to the global `fetch`. */
  fetchImpl?: FetchImpl;
}

export class HttpClient {
  private readonly baseUrl: string;

  private readonly timeoutMs: number;

  private readonly retry: RetryConfig;

  private readonly logger: Logger;

  private readonly fetchImpl: FetchImpl;

  constructor(opts: HttpClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.retry = opts.retry ?? DEFAULT_RETRY;
    this.logger = opts.logger ?? { debug: () => {}, warn: () => {} };
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  async postJson(
    path: string,
    body?: Record<string, unknown>,
    headers?: Record<string, string>,
  ): Promise<HttpResponse> {
    return this.request('POST', path, {
      body: JSON.stringify(body ?? {}),
      headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
      logBody: body,
    });
  }

  async postForm(
    path: string,
    data: Record<string, string | string[]>,
    headers?: Record<string, string>,
  ): Promise<HttpResponse> {
    // Array values are appended as repeated params (e.g. audience=a&audience=b).
    const params = new URLSearchParams();
    Object.entries(data).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
      else params.append(key, value);
    });
    return this.request('POST', path, {
      body: params.toString(),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...(headers ?? {}) },
      logBody: data,
    });
  }

  private async request(
    method: string,
    path: string,
    opts: { body?: string; headers: Record<string, string>; logBody?: Record<string, unknown> },
  ): Promise<HttpResponse> {
    const url = `${this.baseUrl}${path}`;
    let lastErr: unknown;

    for (let attempt = 1; attempt <= this.retry.attempts; attempt += 1) {
      this.logger.debug(
        `descope request ${method} ${path} body=`,
        redact(opts.logBody),
        `(attempt ${attempt})`,
      );

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      let resp: Response;
      try {
        // eslint-disable-next-line no-await-in-loop
        resp = await this.fetchImpl(url, {
          method,
          body: opts.body,
          headers: opts.headers,
          signal: controller.signal,
        });
      } catch (err) {
        lastErr = err;
        clearTimeout(timer);
        if (attempt < this.retry.attempts) {
          // eslint-disable-next-line no-await-in-loop
          await sleep(this.retry.backoffMs * attempt);
          // eslint-disable-next-line no-continue
          continue;
        }
        throw new AgentAuthError(`HTTP transport error calling ${path}: ${String(err)}`);
      } finally {
        clearTimeout(timer);
      }

      if (this.retry.retryStatuses.includes(resp.status) && attempt < this.retry.attempts) {
        // eslint-disable-next-line no-await-in-loop
        await sleep(this.retry.backoffMs * attempt);
        // eslint-disable-next-line no-continue
        continue;
      }

      // eslint-disable-next-line no-await-in-loop
      const text = await resp.text();
      let json: any = null;
      try {
        json = text ? JSON.parse(text) : null;
      } catch {
        json = null;
      }
      this.logger.debug(`descope response ${method} ${path} -> ${resp.status}`);
      return { statusCode: resp.status, ok: resp.ok, json, text };
    }

    throw new AgentAuthError(`HTTP request to ${path} failed: ${String(lastErr)}`);
  }
}

export { sleep };
