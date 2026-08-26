import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { PublicShell } from "@/features/shell/components/public-shell";

vi.mock("next/navigation", () => ({ usePathname: () => "/login" }));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
}));

async function renderShell(node: React.ReactNode) {
  return render(<I18nProvider locale="es">{node}</I18nProvider>);
}

describe("PublicShell (design D3, landing-public D3)", () => {
  it("renders the brand, theme+locale switchers and footer with no center slot", async () => {
    const { container } = await renderShell(
      await PublicShell({ children: <div data-testid="content">contenido</div> }),
    );

    expect(await screen.findByTestId("content")).toBeInTheDocument();
    // The brand lives inside the topbar `<header>`.
    expect(container.querySelector("header")).not.toBeNull();
    // No center slot is rendered when `marketingNav` is omitted.
    expect(container.querySelector('[data-testid="marketing-nav"]')).toBeNull();
    // The footer (version labels) is present.
    expect(container.querySelector("footer")).not.toBeNull();
  });

  it("renders the supplied marketing nav inside the topbar center slot when provided", async () => {
    const { container } = await renderShell(
      await PublicShell({
        marketingNav: <div data-testid="marketing-nav" />,
        children: <div data-testid="content">contenido</div>,
      }),
    );

    const nav = await screen.findByTestId("marketing-nav");
    expect(nav).toBeInTheDocument();
    // The marketing nav lands inside the topbar `<header>` element — between
    // the brand container and the locale/theme switchers.
    expect(container.querySelector("header")?.contains(nav)).toBe(true);
  });
});
