import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { LandingFooter } from "@/features/landing/components/landing-footer";

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

/**
 * R3.3 / D8: `Pricing`, `Portfolio`, `Team` and `Sign Up` are deliberately NOT
 * rendered because their pages do not exist yet. The footer columns
 * (`footer.product[]`, `footer.company[]`, `footer.legal[]`) are reserved in
 * the catalogue and stay empty today; this test pins the invariant so a future
 * change that adds a forbidden link fails here, not in production.
 */
const FORBIDDEN_LINKS = ["Pricing", "Portfolio", "Team", "Sign Up"];

describe("LandingFooter (R3.3, design D8)", () => {
  it("renders only the copyright and the empty-columns placeholder, never Pricing|Portfolio|Team|Sign Up (es)", async () => {
    cookie.value = "es";
    const { container } = render(
      <I18nProvider locale="es">{await LandingFooter()}</I18nProvider>,
    );

    // The copyright from the catalogue lands.
    expect(screen.getByText(/AutoHostAI/)).toBeInTheDocument();

    // The reserved empty-columns placeholder is the structural marker for R3.3
    // ("footer.legal[] is empty in both per R3.3 — no Pricing/Portfolio/Team/Sign Up").
    expect(container.querySelector("[data-empty-footer-columns]")).not.toBeNull();

    const text = container.textContent || "";
    for (const word of FORBIDDEN_LINKS) {
      expect(text, `forbidden link rendered: ${word}`).not.toContain(word);
    }

    // The footer renders no <a> elements at all today — there are no
    // destinations. A future entry that adds a link to a forbidden page is the
    // regression this test catches; the assertion above pins that no <a>
    // carries forbidden text regardless of where it lands.
    expect(container.querySelector("footer")?.querySelectorAll("a").length ?? 0).toBe(0);
  });

  it("never renders Pricing|Portfolio|Team|Sign Up in English either", async () => {
    cookie.value = "en";
    const { container } = render(
      <I18nProvider locale="en">{await LandingFooter()}</I18nProvider>,
    );

    const text = container.textContent || "";
    for (const word of FORBIDDEN_LINKS) {
      expect(text, `forbidden link rendered: ${word}`).not.toContain(word);
    }
  });
});