import { beforeEach, describe, expect, it, vi } from "vitest";

import { getA11yViolations, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { CleanerShell } from "@/features/shell/components/cleaner-shell";
import { TechnicianShell } from "@/features/shell/components/technician-shell";
import { PublicShell } from "@/features/shell/components/public-shell";
import { GuestShell } from "@/features/shell/components/guest-shell";

const nav = vi.hoisted(() => ({ pathname: "/cleaner" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
}));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: unknown;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : "#"} {...props}>
      {children}
    </a>
  ),
}));

async function renderShell(node: React.ReactNode) {
  return render(<I18nProvider locale="es">{node}</I18nProvider>);
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("CleanerShell (D6/D9, task 6.5)", () => {
  it("renders a topbar-only chrome with no invented bottom nav or sidebar", async () => {
    nav.pathname = "/cleaner";
    await renderShell(await CleanerShell({ children: <div>tareas</div> }));
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Navegación principal" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Mis tareas")).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    nav.pathname = "/cleaner";
    const { container } = await renderShell(
      await CleanerShell({ children: <div>tareas</div> }),
    );
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("TechnicianShell (D6/D9, task 6.6)", () => {
  it("renders a topbar-only chrome and uses the /tech context", async () => {
    nav.pathname = "/tech";
    await renderShell(
      await TechnicianShell({ children: <div>incidencias</div> }),
    );
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Navegación principal" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Mis incidencias")).toBeInTheDocument();
  });
});

describe("PublicShell (D3/D9, task 6.7)", () => {
  it("renders minimal chrome with no private navigation", async () => {
    nav.pathname = "/login";
    await renderShell(await PublicShell({ children: <div>login</div> }));
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Navegación principal" }),
    ).not.toBeInTheDocument();
  });
});

describe("version badge placement (change app-version-visibility, R3.2/R3.7)", () => {
  it("shows the badge on the login shell, where there is no session yet", async () => {
    // R3.2: this is the surface that matters most for diagnosis — if the app is broken
    // you may not be able to get past it, and you still need to know what is deployed.
    nav.pathname = "/login";
    await renderShell(await PublicShell({ children: <div>login</div> }));
    expect(screen.getByTestId("version-badge")).toBeInTheDocument();
  });

  it("shows the badge on the field shells", async () => {
    nav.pathname = "/cleaner";
    const cleaner = await renderShell(
      await CleanerShell({ children: <div>tareas</div> }),
    );
    expect(
      cleaner.container.querySelector('[data-testid="version-badge"]'),
    ).not.toBeNull();
    cleaner.unmount();

    nav.pathname = "/tech";
    await renderShell(
      await TechnicianShell({ children: <div>incidencias</div> }),
    );
    expect(screen.getByTestId("version-badge")).toBeInTheDocument();
  });

  it("does NOT show it on the guest portal", async () => {
    // R3.7: `/guest/[token]` is a surface for people outside the operation. The build
    // version tells them nothing and is not theirs to see — a scoped reading of
    // "visible across the shell" that the change records explicitly.
    nav.pathname = "/guest/secret-token-123";
    const { container } = await renderShell(
      await GuestShell({ children: <div>portal</div> }),
    );
    expect(container.querySelector('[data-testid="version-badge"]')).toBeNull();
  });
});

describe("GuestShell (D3/D9, task 6.7)", () => {
  it("renders isolated chrome and never shows the token", async () => {
    nav.pathname = "/guest/secret-token-123";
    const { container } = await renderShell(
      await GuestShell({ children: <div>portal</div> }),
    );
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(container.textContent).not.toContain("secret-token-123");
    expect(
      screen.queryByRole("navigation", { name: "Navegación principal" }),
    ).not.toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    nav.pathname = "/guest/secret-token-123";
    const { container } = await renderShell(
      await GuestShell({ children: <div>portal</div> }),
    );
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
