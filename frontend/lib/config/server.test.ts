import { afterEach, describe, expect, it, vi } from "vitest";

// next/headers is only usable inside a request; getServerConfig never calls
// cookies(), but importing the module pulls it in, so stub it.
vi.mock("next/headers", () => ({ cookies: vi.fn() }));

import { getServerConfig } from "@/lib/config/server";

describe("getServerConfig (D15)", () => {
  const original = { ...process.env };
  afterEach(() => {
    process.env = { ...original };
  });

  it("reads BACKEND_INTERNAL_URL when present", () => {
    process.env.BACKEND_INTERNAL_URL = "http://backend:8000";
    expect(getServerConfig().backendInternalUrl).toBe("http://backend:8000");
  });

  it("leaves the backend URL undefined when unset (shell needs no backend)", () => {
    delete process.env.BACKEND_INTERNAL_URL;
    expect(getServerConfig().backendInternalUrl).toBeUndefined();
  });
});
