import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `server-only` is aliased to a no-op stub in `vitest.config.ts`.

const cookieMap = vi.hoisted(
  () => new Map<string, { value: string } | undefined>(),
);
const deleteCalls = vi.hoisted(() => [] as string[]);

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => cookieMap.get(name),
    delete: (name: string) => {
      deleteCalls.push(name);
      cookieMap.set(name, undefined);
    },
  }),
}));

const redirectMock = vi.hoisted(() =>
  vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
);
vi.mock("next/navigation", () => ({ redirect: redirectMock }));

const serverFetchMock = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api/server-client", () => ({
  serverFetch: serverFetchMock,
}));

// Mock the landing pieces so the page renders without pulling in the whole
// landing feature.
vi.mock("@/features/landing", () => ({
  LandingView: () => null,
  MarketingNav: () => null,
}));
vi.mock("@/features/shell/components/public-shell", () => ({
  PublicShell: ({ children }: { children: React.ReactNode }) => children,
}));

import { ApiError } from "@/lib/api/errors";
import RootPage from "./page";

describe("RootPage (R4)", () => {
  beforeEach(() => {
    cookieMap.clear();
    deleteCalls.length = 0;
    serverFetchMock.mockReset();
    redirectMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the landing WITHOUT calling serverFetch when the cookie is absent (R4 #1)", async () => {
    cookieMap.set("autohostai.session.present", undefined);

    await expect(RootPage()).resolves.toBeDefined();
    expect(serverFetchMock).not.toHaveBeenCalled();
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("redirects to /dashboard when serverFetch resolves 2xx (R4 #3)", async () => {
    cookieMap.set("autohostai.session.present", { value: "1" });
    serverFetchMock.mockResolvedValueOnce({
      id: "user-1",
      role: "CLEANER",
    });

    await expect(RootPage()).rejects.toThrow("REDIRECT:/dashboard");
    expect(redirectMock).toHaveBeenCalledWith("/dashboard", "replace");
    expect(serverFetchMock).toHaveBeenCalledWith("/api/v1/auth/me", {
      forwardCookies: true,
      timeoutMs: 2000,
    });
    expect(deleteCalls).toEqual([]);
  });

  it("deletes the cookie and renders the landing when serverFetch throws ApiError(401) (R4 #4)", async () => {
    cookieMap.set("autohostai.session.present", { value: "1" });
    serverFetchMock.mockRejectedValueOnce(
      new ApiError({
        code: "UNAUTHORIZED",
        message: "no token",
        status: 401,
      }),
    );

    await expect(RootPage()).resolves.toBeDefined();
    expect(deleteCalls).toEqual(["autohostai.session.present"]);
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("redirects to /dashboard when serverFetch rejects with ApiError(500) (R4 #5)", async () => {
    cookieMap.set("autohostai.session.present", { value: "1" });
    serverFetchMock.mockRejectedValueOnce(
      new ApiError({
        code: "INTERNAL_ERROR",
        message: "upstream",
        status: 500,
      }),
    );

    await expect(RootPage()).rejects.toThrow("REDIRECT:/dashboard");
    expect(deleteCalls).toEqual([]);
  });

  it("redirects to /dashboard when serverFetch throws a non-ApiError (timeout, network) (R4 #5)", async () => {
    cookieMap.set("autohostai.session.present", { value: "1" });
    serverFetchMock.mockRejectedValueOnce(new Error("aborted"));

    await expect(RootPage()).rejects.toThrow("REDIRECT:/dashboard");
    expect(deleteCalls).toEqual([]);
  });
});