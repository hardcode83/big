import { parseApiError } from "./errors";

/**
 * Centralized fetch transport (design D12). It is deliberately generic: it knows
 * about a base URL, a JSON envelope error shape, and documented extension points
 * for future auth — but no endpoints, DTOs, tokens, or business logic. Responses
 * are returned as `unknown`; each feature validates and types its own contract.
 * The transport never reads Zustand or any UI store.
 */
export interface ApiClientOptions {
  baseUrl: string;
  /** Contributes request headers (extension point for future auth). */
  getHeaders?: () => HeadersInit | Promise<HeadersInit>;
  /** Invoked on a 401 response (extension point for future token refresh). */
  onUnauthorized?: (response: Response) => void | Promise<void>;
  /** Injectable fetch, primarily for testing. Defaults to global fetch. */
  fetchImpl?: typeof fetch;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

export interface ApiClient {
  request(path: string, options?: RequestOptions): Promise<unknown>;
}

function joinUrl(baseUrl: string, path: string): string {
  const trimmedBase = baseUrl.replace(/\/+$/, "");
  const trimmedPath = path.replace(/^\/+/, "");
  return `${trimmedBase}/${trimmedPath}`;
}

export function createApiClient(options: ApiClientOptions): ApiClient {
  const doFetch = options.fetchImpl ?? fetch;

  async function request(
    path: string,
    { method = "GET", body, headers, signal }: RequestOptions = {},
  ): Promise<unknown> {
    const finalHeaders = new Headers(headers);

    if (options.getHeaders) {
      const extra = new Headers(await options.getHeaders());
      extra.forEach((value, key) => finalHeaders.set(key, value));
    }

    const hasBody = body !== undefined;
    if (hasBody && !finalHeaders.has("Content-Type")) {
      finalHeaders.set("Content-Type", "application/json");
    }

    const response = await doFetch(joinUrl(options.baseUrl, path), {
      method,
      headers: finalHeaders,
      body: hasBody ? JSON.stringify(body) : undefined,
      signal,
    });

    if (response.status === 401 && options.onUnauthorized) {
      await options.onUnauthorized(response);
    }

    if (!response.ok) {
      throw await parseApiError(response);
    }

    if (response.status === 204) {
      return undefined;
    }

    return (await response.json()) as unknown;
  }

  return { request };
}
