import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { MarketingNav } from "@/features/landing/components/marketing-nav";

const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

/**
 * R3.3 / D8: the marketing nav renders exactly two items — a `Login` link to
 * `/login` and a `#features` anchor that scrolls to the features section of
 * the landing. The four forbidden items (`Pricing`, `Portfolio`, `Team`,
 * `Sign Up`) are NOT rendered because their pages do not exist yet. Below
 * 768 px the `#features` link is hidden (OQ-2, resolved 2026-08-24). This
 * test pins the two-item invariant, the destination of each link, the
 * mobile-hide utility on the anchor, and the absence of forbidden items.
 */
const FORBIDDEN_LINKS = ["Pricing", "Portfolio", "Team", "Sign Up"];

describe("MarketingNav (R3.3, design D8, OQ-2)", () => {
  it("renders exactly two items: a /login link and a #features anchor (es)", async () => {
    cookie.value = "es";
    render(<I18nProvider locale="es">{await MarketingNav()}</I18nProvider>);

    const nav = screen.getByRole("navigation");
    const links = Array.from(nav.querySelectorAll("a"));
    expect(links.length).toBe(2);

    const loginLink = links.find((a) => a.getAttribute("href") === "/login");
    expect(loginLink, "missing /login link").toBeTruthy();

    const featuresLink = links.find((a) => a.getAttribute("href") === "#features");
    expect(featuresLink, "missing #features anchor").toBeTruthy();
  });

  it("hides the #features link below 768 px via the `hidden md:inline-flex` utility", async () => {
    cookie.value = "es";
    const { container } = render(
      <I18nProvider locale="es">{await MarketingNav()}</I18nProvider>,
    );

    const featuresLink = container.querySelector('a[href="#features"]');
    expect(featuresLink).not.toBeNull();
    expect(featuresLink?.className).toMatch(/\bhidden\b/);
    expect(featuresLink?.className).toMatch(/md:inline-flex/);

    // The Login link stays visible at every breakpoint.
    const loginLink = container.querySelector('a[href="/login"]');
    expect(loginLink).not.toBeNull();
    expect(loginLink?.className).not.toMatch(/(^|\s)hidden(\s|$)/);
  });

  it("does not render Pricing, Portfolio, Team, or Sign Up in any locale", async () => {
    for (const locale of ["es", "en"] as const) {
      cookie.value = locale;
      const { container } = render(
        <I18nProvider locale={locale}>{await MarketingNav()}</I18nProvider>,
      );

      const text = container.textContent || "";
      for (const word of FORBIDDEN_LINKS) {
        expect(text, `[${locale}] forbidden link rendered: ${word}`).not.toContain(word);
      }
    }
  });
});