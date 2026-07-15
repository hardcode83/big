import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

import Page from "./page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Home page", () => {
  it("shows backend: ok when the health check succeeds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      }),
    );

    render(await Page());

    expect(screen.getByTestId("backend-status")).toHaveTextContent(
      "backend: ok",
    );
  });

  it("shows backend: ko when the health check fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network error")));

    render(await Page());

    expect(screen.getByTestId("backend-status")).toHaveTextContent(
      "backend: ko",
    );
  });
});
