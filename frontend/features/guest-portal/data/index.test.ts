import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * R5.9 at the composition root: the guest portal's client **structurally cannot** send
 * `Authorization: Bearer`.
 *
 * **Why this file exists, and why it is not a regex.** Task 9.2 asks for "un test que fije que el
 * cliente sigue sin `getHeaders`", and the QA panel of sections 9-10 found no such test: the
 * existing guard in `http-guest-portal-source.test.ts` drives a *hand-built fake* `ApiClient` and
 * greps the source file's text, so it never exercises the real `createApiClient({ baseUrl: "" })`
 * in `index.ts`. Every other test in this feature mocks `@/features/guest-portal/data` wholesale,
 * so the composition root was covered by nothing at all.
 *
 * A source-text assertion would not close it either: it proves only that this file does not spell
 * out a forbidden identifier today, and a future author could reintroduce the leak through a
 * differently named helper, a spread, or a closure, while the guard stayed green. So this test
 * asserts the **behaviour** instead — with a real staff session live in the same runtime, an
 * actual request from the guest client carries no `Authorization` header. That is the property
 * R5.9 states, and it survives any refactor that keeps the effect while changing the spelling.
 *
 * The `fetch` stub has to be installed **before** the module is imported: `createApiClient`
 * resolves `options.fetchImpl ?? fetch` once, when the client is built, and `index.ts` builds its
 * client at module scope.
 */
describe("the guest portal's composition root (R5.9)", () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.resetModules();
  });

  async function captureRequest() {
    const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
    globalThis.fetch = vi.fn(async (url: unknown, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as unknown as typeof fetch;

    // Imported after the stub is in place, and after `resetModules`, so the client is built
    // against it rather than against whatever a previous test left behind.
    const { setSessionTokens, clearSessionTokens } = await import("@/lib/auth/session-store");
    const { getGuestPortalDataSource } = await import("@/features/guest-portal/data");

    // A staff session, live in the same JavaScript runtime — the situation in which a client
    // that *could* read the session would leak it.
    setSessionTokens({ accessToken: "staff-access-token", refreshToken: "staff-refresh-token" });
    try {
      await getGuestPortalDataSource().getStayInfo("opaque-guest-token");
    } finally {
      clearSessionTokens();
    }
    return calls;
  }

  it("sends no Authorization header even with a staff session live in the same runtime", async () => {
    const calls = await captureRequest();

    expect(calls).toHaveLength(1);
    const headers = new Headers(calls[0].init?.headers);
    expect(headers.get("Authorization")).toBeNull();
    expect(JSON.stringify(calls[0].init?.headers ?? {})).not.toContain("staff-access-token");
  });

  it("carries the guest token only in the path, never in a header", async () => {
    const calls = await captureRequest();

    expect(calls[0].url).toContain("/api/v1/guest/info/opaque-guest-token");
    const headers = new Headers(calls[0].init?.headers);
    headers.forEach((value) => expect(value).not.toContain("opaque-guest-token"));
  });
});
