import { afterEach, describe, expect, it, vi } from "vitest";

import { createAuthenticatedClients } from "./authenticated-client";
import { DEFAULT_LOCALE } from "@/lib/config/constants";
import { getActiveLocale, setActiveLocale } from "@/lib/i18n/active-locale";
import { clearSessionTokens, setSessionTokens } from "@/lib/auth/session-store";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("authenticated ApiClient sends X-Locale (R1.4, design D6)", () => {
  afterEach(() => {
    clearSessionTokens();
    setActiveLocale(DEFAULT_LOCALE);
  });

  it("carries the active locale on every request, without any session", async () => {
    setActiveLocale("en");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
    const { apiClient } = createAuthenticatedClients({
      apiBaseUrl: "https://api.example.com",
      fetchImpl,
    });

    await apiClient.request("/health");

    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Locale")).toBe("en");
  });

  it("updates the header's value when the active locale changes, without needing a new client", async () => {
    setActiveLocale("es");
    const fetchImpl = vi.fn().mockImplementation(async () => jsonResponse({ ok: 1 }));
    const { apiClient } = createAuthenticatedClients({
      apiBaseUrl: "https://api.example.com",
      fetchImpl,
    });

    await apiClient.request("/health");
    expect(
      new Headers((fetchImpl.mock.calls[0][1] as RequestInit).headers).get(
        "X-Locale",
      ),
    ).toBe("es");

    setActiveLocale("en");
    await apiClient.request("/health");
    expect(
      new Headers((fetchImpl.mock.calls[1][1] as RequestInit).headers).get(
        "X-Locale",
      ),
    ).toBe(getActiveLocale());
    expect(
      new Headers((fetchImpl.mock.calls[1][1] as RequestInit).headers).get(
        "X-Locale",
      ),
    ).toBe("en");
  });

  it("sends both X-Locale and Authorization when a session is present", async () => {
    setActiveLocale("en");
    setSessionTokens({ accessToken: "access-1", refreshToken: "refresh-1" });
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
    const { apiClient } = createAuthenticatedClients({
      apiBaseUrl: "https://api.example.com",
      fetchImpl,
    });

    await apiClient.request("/health");

    const headers = new Headers(
      (fetchImpl.mock.calls[0][1] as RequestInit).headers,
    );
    expect(headers.get("X-Locale")).toBe("en");
    expect(headers.get("Authorization")).toBe("Bearer access-1");
  });

  it("still sends X-Locale when there is no session (no Authorization header)", async () => {
    setActiveLocale("es");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: 1 }));
    const { apiClient } = createAuthenticatedClients({
      apiBaseUrl: "https://api.example.com",
      fetchImpl,
    });

    await apiClient.request("/health");

    const headers = new Headers(
      (fetchImpl.mock.calls[0][1] as RequestInit).headers,
    );
    expect(headers.get("X-Locale")).toBe("es");
    expect(headers.has("Authorization")).toBe(false);
  });
});
