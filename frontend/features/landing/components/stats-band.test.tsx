import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { StatsBand } from "@/features/landing/components/stats-band";

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

describe("StatsBand (R5.1, R5.2, design D6)", () => {
  it("renders the two product statements, exactly as the locale catalogue says", async () => {
    cookie.value = "es";
    const { container } = render(
      <I18nProvider locale="es">{await StatsBand()}</I18nProvider>,
    );

    // The Spanish catalogue names — R5.1 wording chosen 2026-08-24
    // (proposal OQ-1, resolved by Jose): two product statements, no
    // numbers, no percentages.
    expect(screen.getByText("Una consola para tu operación")).toBeInTheDocument();
    expect(
      screen.getByText("Construido sobre la pila que tu equipo ya confía"),
    ).toBeInTheDocument();

    // The maqueta's "500+" / "99%" pair (R5.2) and ANY other digit must
    // not appear — the band carries product statements, not invented
    // metrics.
    expect(container.textContent || "").not.toMatch(/\d/);
    expect(container.textContent || "").not.toContain("Satisfacción");
    expect(container.textContent || "").not.toContain("500");
  });

  it("localises the two lines to English", async () => {
    cookie.value = "en";
    render(
      <I18nProvider locale="en">{await StatsBand()}</I18nProvider>,
    );

    expect(screen.getByText("One console for your operation")).toBeInTheDocument();
    expect(
      screen.getByText("Built on the stack your team already trusts"),
    ).toBeInTheDocument();
  });
});
