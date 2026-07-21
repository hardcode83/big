import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { RoutePlaceholder } from "@/features/shell/components/route-placeholder";

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

describe("RoutePlaceholder (D8/D19, tasks 7.x)", () => {
  it("renders the localized planned placeholder (es fallback)", async () => {
    cookie.value = undefined;
    render(await RoutePlaceholder({ routeId: "dashboard" }));
    expect(screen.getByRole("heading", { name: "Panel" })).toBeInTheDocument();
    expect(screen.getByText("En preparación")).toBeInTheDocument();
    expect(
      screen.getByText(/prevista pero todavía no está disponible/),
    ).toBeInTheDocument();
  });

  it("renders English copy when the locale cookie is en", async () => {
    cookie.value = "en";
    render(await RoutePlaceholder({ routeId: "dashboard" }));
    expect(
      screen.getByRole("heading", { name: "Dashboard" }),
    ).toBeInTheDocument();
    expect(screen.getByText("In preparation")).toBeInTheDocument();
  });

  it("uses a generic localized title for dynamic routes and never an id", async () => {
    cookie.value = undefined;
    const { container } = render(
      await RoutePlaceholder({ routeId: "property-detail" }),
    );
    expect(
      screen.getByRole("heading", { name: "Detalle de propiedad" }),
    ).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d/);
  });

  it("renders nothing for an unknown route id", async () => {
    expect(await RoutePlaceholder({ routeId: "does-not-exist" })).toBeNull();
  });
});
