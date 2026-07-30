import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ cookies: vi.fn() }));

import { GET, __resetVersionCache } from "./route";

const original = { ...process.env };

beforeEach(() => {
  process.env.BACKEND_INTERNAL_URL = "http://backend:8000";
  process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
  vi.restoreAllMocks();
  __resetVersionCache();
});

afterEach(() => {
  process.env = { ...original };
});

async function body() {
  return (await (await GET()).json()) as {
    frontend: string | null;
    backend: string | null;
  };
}

describe("GET /deployment/version (R5.1-R5.6)", () => {
  it("returns both version strings when the backend answers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({ version: "0.1.0+2026-07-30.a2f3c1d", pr: 42 }),
      ),
    );

    expect(await body()).toEqual({
      frontend: "0.1.0+2026-07-30.a2f3c1d",
      backend: "0.1.0+2026-07-30.a2f3c1d",
    });
  });

  it("reads the backend over the internal compose URL, not from the browser", async () => {
    // R5.1/R5.2: the request must leave from the Next server towards
    // BACKEND_INTERNAL_URL. Asserting the URL is what pins that down.
    const seen: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL) => {
        seen.push(String(url));
        return Response.json({ version: "x" });
      }),
    );

    await GET();

    expect(seen).toEqual(["http://backend:8000/version"]);
  });

  it("reports the backend as unknown when it refuses the connection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );

    expect(await body()).toEqual({
      frontend: "0.1.0+2026-07-30.a2f3c1d",
      backend: null,
    });
  });

  it("reports the backend as unknown on a non-2xx answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 503 })),
    );

    expect((await body()).backend).toBeNull();
  });

  it("reports the backend as unknown when the request is aborted by the timeout", async () => {
    // R5.5: a hung backend must not hang the panel. The handler passes an
    // AbortSignal.timeout, so the rejection it has to survive is an AbortError.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("The operation was aborted.", "TimeoutError");
      }),
    );

    expect((await body()).backend).toBeNull();
  });

  it("survives a malformed body without failing the request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not json", { status: 200 })),
    );

    const response = await GET();
    expect(response.status).toBe(200);
    expect(
      ((await response.json()) as { backend: unknown }).backend,
    ).toBeNull();
  });

  it("ignores a non-string version field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ version: { nested: "nope" } })),
    );

    expect((await body()).backend).toBeNull();
  });

  it("reports unknown without any request when no backend URL is configured", async () => {
    delete process.env.BACKEND_INTERNAL_URL;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    expect((await body()).backend).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("NEVER returns the PR, the repository URL, the run id or the ref", async () => {
    // R5.6/R3.6. The Cloudflare Tunnel routes to frontend:3000, so this path is
    // publicly reachable — only version strings may cross it. Everything sensitive is
    // present in the environment here on purpose, so the assertion means something.
    process.env.BUILD_PR = "42";
    process.env.BUILD_RUN_ID = "1234567890";
    process.env.BUILD_REF = "refs/heads/main";
    process.env.REPO_URL = "https://github.com/autohostai-labs/AutoHostAI";
    process.env.BUILD_COMMIT = "a2f3c1d3f9b2000000000000000000000000000f";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          version: "0.1.0+2026-07-30.a2f3c1d",
          commit: "a2f3c1d3f9b2000000000000000000000000000f",
          pr: 42,
          run_id: "1234567890",
          ref: "refs/heads/main",
        }),
      ),
    );

    const response = await GET();
    const raw = await response.text();

    expect(Object.keys(JSON.parse(raw) as object).sort()).toEqual([
      "backend",
      "frontend",
    ]);
    expect(raw).not.toContain("github.com");
    expect(raw).not.toContain("autohostai-labs");
    expect(raw).not.toContain("1234567890");
    expect(raw).not.toContain("refs/heads/main");
    expect(raw).not.toContain("a2f3c1d3f9b2000000000000000000000000000f");
  });
});
