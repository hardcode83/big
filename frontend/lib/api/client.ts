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

type ParametersFor<Operation> = Operation extends { parameters?: infer Parameters }
  ? Parameters
  : never;

type QueryFor<Operation> = ParametersFor<Operation> extends {
  query?: infer Query;
}
  ? Query
  : never;

type PathFor<Operation> = ParametersFor<Operation> extends {
  path: infer Path;
}
  ? Path
  : never;

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
  /**
   * Multipart body, mutually exclusive with `body`. When present the client
   * sends the `FormData` as-is and does NOT set a default `Content-Type`: the
   * browser has to write it itself so the header carries the `boundary`
   * (design D2). A separate field and not `body` because `RequestBodyFor<…>`
   * only extracts `content["application/json"]`, which is `never` for a
   * multipart-only route.
   */
  formData?: FormData;
  headers?: HeadersInit;
  pathParams?: Record<string, string | number>;
  /**
   * `boolean` is in here because the argument is the **intersection** of this
   * `Record` with the operation's own `QueryFor<…>`: a query parameter the
   * contract declares as `boolean | null` — `active` on
   * `GET /api/v1/pricing-rules` is the first in the tree — satisfies the second
   * half and not the first, so it fails to compile without it. Runtime never
   * needed the change: `appendQuery` has always done `String(value)`, and
   * FastAPI parses `true`/`false` (`pricing-web` design D20).
   */
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

type RequestArguments<
  Path extends keyof paths,
  Method extends Uppercase<MethodForPath<Path>>,
> = "get" extends MethodForPath<Path>
  ? [
      options?: RequestOptions<
        RequestBodyFor<OperationFor<Path, Method>>,
        Method
      > & {
        pathParams?: PathFor<OperationFor<Path, Method>>;
        query?: QueryFor<OperationFor<Path, Method>>;
      },
    ]
  : [
      options: RequestOptions<
        RequestBodyFor<OperationFor<Path, Method>>,
        Method
      > & {
        method: Method;
        pathParams?: PathFor<OperationFor<Path, Method>>;
        query?: QueryFor<OperationFor<Path, Method>>;
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

function resolvePath(path: string, pathParams: Record<string, string | number> = {}): string {
  return path.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = pathParams[name];
    if (value === undefined) {
      throw new Error(`Missing path parameter: ${name}`);
    }
    return encodeURIComponent(String(value));
  });
}

function appendQuery(
  path: string,
  query: Record<string, string | number | boolean | null | undefined> = {},
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value));
    }
  }
  const encoded = params.toString();
  return encoded ? `${path}?${encoded}` : path;
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
    const { method, body, formData, headers, pathParams, query, signal } =
      requestArguments[0] ?? {};
    let retryCount = 0;

    while (true) {
      const finalHeaders = new Headers(headers);

      if (options.getHeaders) {
        const extra = new Headers(await options.getHeaders());
        extra.forEach((value, key) => finalHeaders.set(key, value));
      }

      const hasBody = body !== undefined;
      if (hasBody && !formData && !finalHeaders.has("Content-Type")) {
        finalHeaders.set("Content-Type", "application/json");
      }

      const resolvedPath = appendQuery(resolvePath(String(path), pathParams), query);
      const response = await doFetch(joinUrl(options.baseUrl, resolvedPath), {
        method: method ?? "GET",
        headers: finalHeaders,
        // The same `FormData` instance is reused when the loop re-enters after
        // a recovered 401 — it is replayable, unlike a stream.
        body: formData ?? (hasBody ? JSON.stringify(body) : undefined),
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
