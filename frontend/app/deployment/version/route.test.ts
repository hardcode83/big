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
    // R5.5: a hung backend must not hang the panel.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("The operation was aborted.", "TimeoutError");
      }),
    );

    expect((await body()).backend).toBeNull();
  });

  it("actually passes an abort signal that fires, not just a caught rejection", async () => {
    // The QA panel proved the test above was VACUOUS for the wiring: deleting
    // `signal: AbortSignal.timeout(...)` from the fetch left all nine tests green, because
    // the rejection came from the mock and never from a real signal. So assert the signal
    // itself — it exists, it is an AbortSignal, and it aborts once the bound elapses. A
    // regression that drops the timeout leaves a hung backend blocking the panel forever.
    let captured: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string | URL, init?: { signal?: AbortSignal }) => {
        captured = init?.signal;
        return Response.json({ version: "x" });
      }),
    );

    await GET();

    expect(captured).toBeInstanceOf(AbortSignal);
    expect(captured!.aborted).toBe(false);
    // AbortSignal.timeout uses real timers, so wait past the bound rather than faking it.
    await new Promise((resolve) => setTimeout(resolve, 2100));
    expect(captured!.aborted).toBe(true);
  }, 10_000);

  it("serves the memoized answer instead of hitting the backend on every request", async () => {
    // Anonymous and publicly routed: without the cache each internet request would force
    // one internal request on a single VM (security panel, finding 2).
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        return Response.json({ version: "0.1.0+cached" });
      }),
    );

    await GET();
    await GET();
    await GET();

    expect(calls).toBe(1);
  });

  it("offers the answer to the edge with a bounded max-age", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ version: "x" })),
    );

    const response = await GET();

    expect(response.headers.get("Cache-Control")).toBe("public, max-age=30");
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
