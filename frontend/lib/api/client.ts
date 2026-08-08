import type { paths } from "./generated/openapi";
import { parseApiError } from "./errors";

type SuccessfulStatus = 200 | 201 | 202 | 203 | 204 | 205 | 206 | 207 | 208 | 226;

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "OPTIONS" | "HEAD" | "TRACE";

type MethodForPath<Path extends keyof paths> = Extract<
  keyof paths[Path],
  Lowercase<HttpMethod>
>;

type OperationFor<
  Path extends keyof paths,
  Method extends string,
> = paths[Path][Lowercase<Method> & keyof paths[Path]];

type RequestBodyFor<Operation> = Operation extends {
  requestBody?: infer RequestBody;
}
  ? RequestBody extends { content: infer Content }
    ? Content extends { "application/json": infer Body }
      ? Body
      : never
    : never
  : never;

type ResponseBodyFor<Response> = Response extends { content: infer Content }
  ? Content extends object
    ? "application/json" extends keyof Content
      ? Content["application/json"]
      : never
    : never
  : never;

type ResponseFor<Operation> = Operation extends { responses: infer Responses }
  ? Responses extends object
    ? ResponseBodyFor<Responses[Extract<keyof Responses, SuccessfulStatus>]> extends never
      ? undefined
      : ResponseBodyFor<Responses[Extract<keyof Responses, SuccessfulStatus>]>
    : undefined
  : undefined;

export interface ApiClientOptions {
  baseUrl: string;
  /** Contributes request headers, including the current auth session when present. */
  getHeaders?: () => HeadersInit | Promise<HeadersInit>;
  /**
   * Recovers one eligible authenticated request after a 401. Return true to
   * retry the original request once; return false/undefined to surface the 401.
   */
  onUnauthorized?: (context: UnauthorizedContext) => boolean | void | Promise<boolean | void>;
  /** Injectable fetch, primarily for testing. Defaults to global fetch. */
  fetchImpl?: typeof fetch;
}

export interface UnauthorizedContext {
  response: Response;
  path: keyof paths;
  method: Uppercase<MethodForPath<keyof paths>>;
  hadAccessToken: boolean;
  retryCount: number;
}

export interface RequestOptions<Body, Method extends string> {
  method?: Method;
  body?: Body;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

type RequestArguments<
  Path extends keyof paths,
  Method extends Uppercase<MethodForPath<Path>>,
> = "get" extends MethodForPath<Path>
  ? [options?: RequestOptions<RequestBodyFor<OperationFor<Path, Method>>, Method>]
  : [
      options: RequestOptions<RequestBodyFor<OperationFor<Path, Method>>, Method> & {
        method: Method;
      },
    ];

export interface ApiClient {
  request<
    Path extends keyof paths,
    Method extends Uppercase<MethodForPath<Path>> = Uppercase<MethodForPath<Path>>,
  >(
    path: Path,
    ...options: RequestArguments<Path, Method>
  ): Promise<ResponseFor<OperationFor<Path, Method>>>;
}

function joinUrl(baseUrl: string, path: string): string {
  const trimmedBase = baseUrl.replace(/\/+$/, "");
  const trimmedPath = path.replace(/^\/+/, "");
  return `${trimmedBase}/${trimmedPath}`;
}

export function createApiClient(options: ApiClientOptions): ApiClient {
  const doFetch = options.fetchImpl ?? fetch;

  async function request<
    Path extends keyof paths,
    Method extends Uppercase<MethodForPath<Path>> = Uppercase<MethodForPath<Path>>,
  >(
    path: Path,
    ...requestArguments: RequestArguments<Path, Method>
  ): Promise<ResponseFor<OperationFor<Path, Method>>> {
    const { method, body, headers, signal } = requestArguments[0] ?? {};
    let retryCount = 0;

    while (true) {
      const finalHeaders = new Headers(headers);

      if (options.getHeaders) {
        const extra = new Headers(await options.getHeaders());
        extra.forEach((value, key) => finalHeaders.set(key, value));
      }

      const hasBody = body !== undefined;
      if (hasBody && !finalHeaders.has("Content-Type")) {
        finalHeaders.set("Content-Type", "application/json");
      }

      const response = await doFetch(joinUrl(options.baseUrl, String(path)), {
        method: method ?? "GET",
        headers: finalHeaders,
        body: hasBody ? JSON.stringify(body) : undefined,
        signal,
      });

      const hadAccessToken = /^Bearer\s+\S+$/i.test(
        finalHeaders.get("Authorization") ?? "",
      );
      const authEndpoint = new Set([
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
      ]).has(String(path));

      if (
        response.status === 401 &&
        options.onUnauthorized &&
        hadAccessToken &&
        !authEndpoint &&
        retryCount === 0
      ) {
        const recovered = await options.onUnauthorized({
          response,
          path,
          method: (method ?? "GET") as UnauthorizedContext["method"],
          hadAccessToken,
          retryCount,
        });
        if (recovered) {
          retryCount += 1;
          continue;
        }
      }

      if (!response.ok) {
        throw await parseApiError(response);
      }

      if (response.status === 204) {
        return undefined as ResponseFor<OperationFor<Path, Method>>;
      }

      return (await response.json()) as ResponseFor<OperationFor<Path, Method>>;
    }
  }

  return { request };
}
