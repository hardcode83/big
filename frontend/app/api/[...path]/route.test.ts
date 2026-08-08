// @vitest-environment node
//
// Node rather than the project-wide jsdom: this is a server Route Handler and the test
// drives real `Request`/`Response` objects and a streamed body, which jsdom does not
// provide faithfully.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, PATCH, POST, PUT } from "./route";

const BACKEND = "http://backend:8000";
const EDGE_CLIENT_IP = "203.0.113.9";

type FetchCall = { url: string; init: RequestInit & { headers: Headers } };

let calls: FetchCall[];

function stubUpstream(response = new Response("{}", { status: 200 })) {
  const fetchMock = vi.fn(async (url: URL | string, init: RequestInit) => {
    calls.push({
      url: String(url),
      init: { ...init, headers: new Headers(init.headers) },
    });
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** A request as it reaches the handler, i.e. already routed under `/api/`. */
function incoming(
  path: string,
  { method = "GET", headers = {}, body = null as BodyInit | null } = {},
): Request {
  return new Request(`https://autohostai.example${path}`, {
    method,
    headers,
    body,
    ...(body ? { duplex: "half" } : {}),
  } as RequestInit);
}

function context(...segments: string[]) {
  return { params: Promise.resolve({ path: segments }) };
}

beforeEach(() => {
  calls = [];
  process.env.BACKEND_INTERNAL_URL = BACKEND;
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete process.env.BACKEND_INTERNAL_URL;
});

// --- The outbound URL: it cannot be steered outside /api/ (R1.1, R2.1) ---

describe("target URL", () => {
  it("forwards the path verbatim to the internal backend", async () => {
    stubUpstream();

    await GET(incoming("/api/v1/auth/me") as never, context("v1", "auth", "me"));

    expect(calls[0].url).toBe(`${BACKEND}/api/v1/auth/me`);
  });

  it("preserves the query string", async () => {
    stubUpstream();

    await GET(
      incoming("/api/v1/reservations?page=2&status=CONFIRMED") as never,
      context("v1", "reservations"),
    );

    expect(calls[0].url).toBe(`${BACKEND}/api/v1/reservations?page=2&status=CONFIRMED`);
  });

  it("re-encodes a decoded segment canonically", async () => {
    stubUpstream();

    await GET(
      incoming("/api/v1/guest/a%20b") as never,
      context("v1", "guest", "a b"),
    );

    expect(calls[0].url).toBe(`${BACKEND}/api/v1/guest/a%20b`);
  });

  it("keeps a path prefix carried by BACKEND_INTERNAL_URL", async () => {
    process.env.BACKEND_INTERNAL_URL = "http://backend:8000/inner";
    stubUpstream();

    await GET(incoming("/api/v1/auth/me") as never, context("v1", "auth", "me"));

    expect(calls[0].url).toBe("http://backend:8000/inner/api/v1/auth/me");
  });

  it.each([[".."], ["."]])(
    "refuses a %s traversal segment without calling upstream",
    async (segment) => {
      const fetchMock = stubUpstream();

      const response = await GET(
        incoming("/api/v1/auth") as never,
        context("v1", segment, "auth"),
      );

      expect(fetchMock).not.toHaveBeenCalled();
      expect(response.status).toBe(502);
    },
  );

  it.each([
    // The bypass a QA review reproduced live, and the reason the outbound path is
    // rebuilt from decoded segments instead of copied from the pathname. The router
    // splits on LITERAL `/`, so an encoded separator arrives INSIDE one segment and
    // never equals `".."` — while undici decodes it back to `/` on the wire.
    ["encoded traversal to the API root", ["..", "..", "openapi.json"]],
    ["separator smuggled in one segment", ["../../openapi.json"]],
    ["separator plus a real prefix", ["v1", "../../docs"]],
    ["backslash separator", ["..\\..\\openapi.json"]],
    ["bare decoded slash", ["a/b"]],
  ])("refuses %s without calling upstream", async (_label, segments) => {
    const fetchMock = stubUpstream();

    const response = await GET(
      incoming(`/api/${segments.join("/")}`) as never,
      context(...segments),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(response.status).toBe(502);
  });

  it("cannot be steered outside /api/ by any segment content", async () => {
    // The property, stated once over the whole class rather than per payload: whatever
    // the segments are, if a request goes upstream at all its path starts with /api/.
    for (const segments of [
      ["..", "openapi.json"],
      ["../../health"],
      ["v1", "..%2f..%2fdocs"],
      ["v1", "auth", "me"],
      ["v1", "guest", "tok=en+with/chars"],
    ]) {
      calls = [];
      stubUpstream();

      await GET(
        incoming(`/api/${segments.join("/")}`) as never,
        context(...segments),
      );

      for (const call of calls) {
        expect(new URL(call.url).pathname.startsWith("/api/")).toBe(true);
      }
    }
  });

  it("refuses a pathname outside the proxied prefix", async () => {
    const fetchMock = stubUpstream();

    const response = await GET(incoming("/openapi.json") as never, context());

    expect(fetchMock).not.toHaveBeenCalled();
    expect(response.status).toBe(502);
  });

  it("fails closed when the backend URL is not configured", async () => {
    delete process.env.BACKEND_INTERNAL_URL;
    const fetchMock = stubUpstream();

    const response = await GET(incoming("/api/v1/auth/me") as never, context("v1"));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(response.status).toBe(502);
  });
});

// --- Method and body pass through unchanged (R1.1) ---

describe("method and body", () => {
  it.each([
    ["POST", POST],
    ["PUT", PUT],
    ["PATCH", PATCH],
    ["DELETE", DELETE],
  ])("forwards %s with its body", async (method, handler) => {
    stubUpstream();

    await handler(
      incoming("/api/v1/auth/login", {
        method,
        body: '{"email":"a@b.c"}',
        headers: { "content-type": "application/json" },
      }) as never,
      context("v1", "auth", "login"),
    );

    expect(calls[0].init.method).toBe(method);
    expect(calls[0].init.body).not.toBeNull();
    expect(calls[0].init.headers.get("content-type")).toBe("application/json");
  });

  it("sends no body on GET", async () => {
    stubUpstream();

    await GET(incoming("/api/v1/auth/me") as never, context("v1", "auth", "me"));

    expect(calls[0].init.body).toBeNull();
  });

  it("does not follow a redirect from the backend", async () => {
    stubUpstream();

    await GET(incoming("/api/v1/auth/me") as never, context("v1", "auth", "me"));

    expect(calls[0].init.redirect).toBe("manual");
  });

  it("returns the upstream status and body unchanged", async () => {
    stubUpstream(
      new Response('{"error":{"code":"INVALID_CREDENTIALS"}}', {
        status: 401,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await POST(
      incoming("/api/v1/auth/login", { method: "POST", body: "{}" }) as never,
      context("v1", "auth", "login"),
    );

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      error: { code: "INVALID_CREDENTIALS" },
    });
  });
});

// --- Header sanitising: the bypass this handler exists to close (R3.1, R4.2) ---

describe("forwarding headers", () => {
  it.each([
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "forwarded",
    "true-client-ip",
    "x-real-ip",
  ])("never lets a client-supplied %s survive the hop", async (header) => {
    stubUpstream();

    await GET(
      incoming("/api/v1/auth/me", { headers: { [header]: "9.9.9.9" } }) as never,
      context("v1", "auth", "me"),
    );

    expect(calls[0].init.headers.get(header)).toBeNull();
  });

  it("reports the client address the edge observed", async () => {
    stubUpstream();

    await GET(
      incoming("/api/v1/auth/me", {
        headers: { "cf-connecting-ip": EDGE_CLIENT_IP },
      }) as never,
      context("v1", "auth", "me"),
    );

    expect(calls[0].init.headers.get("x-forwarded-for")).toBe(EDGE_CLIENT_IP);
  });

  it("replaces a client-supplied chain rather than appending to it", async () => {
    // The client tries to prepend a hop; the value the backend reads must be only the
    // one the edge observed, or the right-most-untrusted-hop walk would pick the fake.
    stubUpstream();

    await GET(
      incoming("/api/v1/auth/me", {
        headers: {
          "x-forwarded-for": "9.9.9.9",
          "cf-connecting-ip": EDGE_CLIENT_IP,
        },
      }) as never,
      context("v1", "auth", "me"),
    );

    expect(calls[0].init.headers.get("x-forwarded-for")).toBe(EDGE_CLIENT_IP);
  });

  it.each([
    ["not-an-ip"],
    [""],
    ["   "],
    ["999.1.1.1"],
    ["a".repeat(60)],
    // These two PASS Node's `isIP` — measured: `isIP("fe80::1%" + "z".repeat(100))`
    // returns 6. So validating with `isIP` alone would forward a 108-character value
    // that the backend must then throw away.
    [`fe80::1%${"z".repeat(100)}`],
    ["fe80::1%eth0"],
  ])(
    "does not turn %s into a client address",
    async (value) => {
      // A junk value must never become a throttle key or an `audit_logs.actor_ip`,
      // which is VARCHAR(45) and whose domain guard raises past that length.
      stubUpstream();

      await GET(
        incoming("/api/v1/auth/me", { headers: { "cf-connecting-ip": value } }) as never,
        context("v1", "auth", "me"),
      );

      expect(calls[0].init.headers.get("x-forwarded-for")).toBeNull();
    },
  );

  it("sends no client address at all when the edge did not supply one", async () => {
    // The safe failure: the backend falls back to this container's address, which
    // under-counts the throttle rather than letting a caller choose their bucket.
    stubUpstream();

    await GET(incoming("/api/v1/auth/me") as never, context("v1", "auth", "me"));

    expect(calls[0].init.headers.get("x-forwarded-for")).toBeNull();
  });

  it.each(["connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade"])(
    "drops the hop-by-hop header %s",
    async (header) => {
      stubUpstream();

      await GET(
        incoming("/api/v1/auth/me", { headers: { [header]: "x" } }) as never,
        context("v1", "auth", "me"),
      );

      expect(calls[0].init.headers.get(header)).toBeNull();
    },
  );

  it("drops proxy-prefixed headers", async () => {
    stubUpstream();

    await GET(
      incoming("/api/v1/auth/me", {
        headers: { "proxy-authorization": "Basic x" },
      }) as never,
      context("v1", "auth", "me"),
    );

    expect(calls[0].init.headers.get("proxy-authorization")).toBeNull();
  });

  it("forwards the Authorization header, which the API needs", async () => {
    stubUpstream();

    await GET(
      incoming("/api/v1/auth/me", {
        headers: { authorization: "Bearer token" },
      }) as never,
      context("v1", "auth", "me"),
    );

    expect(calls[0].init.headers.get("authorization")).toBe("Bearer token");
  });

  it("lets the runtime set Host from the target URL", async () => {
    stubUpstream();

    await GET(
      incoming("/api/v1/auth/me", { headers: { host: "attacker.example" } }) as never,
      context("v1", "auth", "me"),
    );

    expect(calls[0].init.headers.get("host")).toBeNull();
  });
});

// --- The internal origin must not travel in a redirect (R1.5) ---

describe("upstream redirects", () => {
  it("rewrites an absolute Location on the internal origin to a same-origin path", async () => {
    // Starlette's `redirect_slashes` answers 307 with an absolute URL built from the
    // authority it was addressed by — `backend:8000`. Passing it through told any
    // anonymous caller the internal service name and port, and pointed a real browser at
    // a host it cannot resolve.
    stubUpstream(
      new Response(null, {
        status: 307,
        headers: { location: "http://backend:8000/api/v1/users" },
      }),
    );

    const response = await GET(
      incoming("/api/v1/users") as never,
      context("v1", "users"),
    );

    expect(response.headers.get("location")).toBe("/api/v1/users");
  });

  it("preserves the query string when rewriting a Location", async () => {
    stubUpstream(
      new Response(null, {
        status: 308,
        headers: { location: "http://backend:8000/api/v1/users?page=2" },
      }),
    );

    const response = await GET(
      incoming("/api/v1/users") as never,
      context("v1", "users"),
    );

    expect(response.headers.get("location")).toBe("/api/v1/users?page=2");
  });

  it.each([
    // Dressed as the internal origin.
    ["http://backend:8000//evil.example/x"],
    // Bare scheme-relative: resolves to a FOREIGN origin, so it never reached the
    // same-origin branch at all.
    ["//evil.example/x"],
    // Backslash spellings. The URL parser folds `\` into `/` for special schemes, so each
    // of these resolves to `http://evil.example/x` — and the first is the one a
    // shape-matching deny-list missed, because it does not begin with `/`.
    ["\\\\evil.example/x"],
    ["/\\evil.example/x"],
    ["\\/evil.example/x"],
    // Any other origin. Dropped too: default-deny means the proxy emits only what it
    // built itself.
    ["https://example.test/somewhere"],
    ["mailto:someone@example.test"],
  ])("emits no Location for %s", async (location) => {
    stubUpstream(new Response(null, { status: 302, headers: { location } }));

    const response = await GET(incoming("/api/v1/x") as never, context("v1", "x"));

    expect(response.headers.get("location")).toBeNull();
  });

  it("resolves a relative Location against the proxied path", async () => {
    // A relative `Location` is legal and resolves same-origin, so it survives — rewritten
    // to the path the client should follow on the public origin.
    stubUpstream(
      new Response(null, { status: 302, headers: { location: "elsewhere" } }),
    );

    const response = await GET(
      incoming("/api/v1/users") as never,
      context("v1", "users"),
    );

    expect(response.headers.get("location")).toBe("/api/v1/elsewhere");
  });

  it("emits only a Location it constructed itself, never the upstream bytes", async () => {
    // The property, stated positively: whatever comes back, if a Location survives it is
    // a single-slash same-origin path built from the resolved URL.
    for (const location of [
      "http://backend:8000/api/v1/users",
      "/api/v1/users",
      "http://backend:8000//evil.example/x",
      "https://example.test/x",
    ]) {
      stubUpstream(new Response(null, { status: 307, headers: { location } }));

      const response = await GET(incoming("/api/v1/x") as never, context("v1", "x"));
      const emitted = response.headers.get("location");

      if (emitted !== null) {
        expect(emitted.startsWith("/")).toBe(true);
        expect(emitted.startsWith("//")).toBe(false);
        expect(emitted).not.toContain("evil.example");
        expect(emitted).not.toContain("backend");
      }
    }
  });

  it("does not pass the upstream server header through", async () => {
    stubUpstream(new Response("{}", { status: 200, headers: { server: "uvicorn" } }));

    const response = await GET(incoming("/api/v1/x") as never, context("v1", "x"));

    expect(response.headers.get("server")).toBeNull();
  });
});

// --- Failure of the hop itself (R1.5, design D6) ---

describe("upstream failure", () => {
  it("answers 502 in the PRD §23 envelope with a published error code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connect ECONNREFUSED 172.18.0.4:8000");
      }),
    );

    const response = await GET(
      incoming("/api/v1/auth/me") as never,
      context("v1", "auth", "me"),
    );

    expect(response.status).toBe(502);
    // INTERNAL_ERROR and not a code of the proxy's own: `error_codes.py` is the single
    // source of these values and the OpenAPI contract publishes them as an enum, so an
    // invented code would make the frontend's exhaustive switch cover the wrong set.
    await expect(response.json()).resolves.toEqual({
      error: {
        code: "INTERNAL_ERROR",
        message: expect.any(String),
        details: {},
      },
    });
  });

  it("leaks neither the internal service name, port, nor the reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("connect ECONNREFUSED backend:8000");
      }),
    );

    const response = await GET(
      incoming("/api/v1/auth/me") as never,
      context("v1", "auth", "me"),
    );
    const body = await response.text();

    expect(body).not.toContain("backend");
    expect(body).not.toContain("8000");
    expect(body).not.toContain("ECONNREFUSED");
  });
});
