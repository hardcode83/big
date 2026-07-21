import { describe, expect, it } from "vitest";

import { getQueryClient, makeQueryClient } from "@/lib/query/query-client";

describe("query client (D11)", () => {
  it("returns a stable instance in the browser environment", () => {
    // jsdom is treated as a browser by TanStack Query (isServer === false).
    expect(getQueryClient()).toBe(getQueryClient());
  });

  it("disables automatic mutation retries by default", () => {
    const client = makeQueryClient();
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
  });

  it("does not run any query on creation", () => {
    const client = makeQueryClient();
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });
});
