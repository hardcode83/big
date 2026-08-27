import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
  within,
} from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { WorkspaceShell } from "@/features/shell/components/workspace-shell";
import { useShellUiStore } from "@/features/shell/state/use-shell-ui-store";

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  // `LocaleSwitcher` calls `router.refresh()` after writing the locale cookie
  // (public-zone-hardening R1 + design D1). The shell tests never trigger the
  // switcher, so a no-op spy is enough to keep the import graph intact.
  useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ status: "authenticated" }),
}));
vi.mock("@/lib/auth/session-store", () => ({
  getSessionTokens: () => ({ accessToken: "test" }),
}));
vi.mock("@/lib/config/runtime-config-provider", () => ({
  useRuntimeConfig: () => ({ apiBaseUrl: "" }),
}));
// Server t (getServerT) reads the locale cookie; default to the es fallback.
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

async function renderShell() {
  return render(
    <I18nProvider locale="es">
      {await WorkspaceShell({ children: <div>contenido</div> })}
    </I18nProvider>,
  );
}

beforeEach(() => {
  nav.pathname = "/dashboard";
  window.localStorage.clear();
  useShellUiStore.setState({
    sidebarCollapsedByProfile: {},
    tabletNavOpen: false,
    mobileMoreOpen: false,
  });
});

afterEach(() => {
  window.localStorage.clear();
});

describe("WorkspaceShell version badge (change app-version-visibility, R2.1)", () => {
  it("renders the badge, and it is the shell that actually has a fixed bottom nav", async () => {
    // The QA panel found this untested: WorkspaceShell is the ONLY shell that renders
    // BottomNavigation, so it is the only surface where "footer hidden behind the fixed
    // bar" can happen — and it was the one shell no test checked for the badge at all.
    const { container } = await renderShell();

    const badge = screen.getByTestId("version-badge");
    expect(badge).toBeInTheDocument();

    const footer = container.querySelector("footer")!;
    const fixedNav = container.querySelector('nav[class*="fixed"]')!;
    expect(footer).not.toBeNull();
    expect(fixedNav).not.toBeNull();
    // Footer before the fixed nav, and inside the column that reserves its height.
    expect(
      footer.compareDocumentPosition(fixedNav) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(footer.parentElement?.className).toContain("pb-16");
  });
});

describe("WorkspaceShell (D3/D6/D9)", () => {
  it("renders shell landmarks and the skip link", async () => {
    await renderShell();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(
      screen.getByRole("link", { name: "Saltar al contenido" }),
    ).toBeInTheDocument();
  });

  it("shows workspace destinations and never Cleaner/Technician", async () => {
    await renderShell();
    expect(
      screen.getAllByRole("link", { name: "Panel" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("link", { name: "Propiedades" }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByRole("link", { name: "Mis tareas" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Mis incidencias" }),
    ).not.toBeInTheDocument();
  });

  it("marks the active destination with aria-current", async () => {
    await renderShell();
    const dashboardLinks = screen.getAllByRole("link", { name: "Panel" });
    expect(
      dashboardLinks.some(
        (link) => link.getAttribute("aria-current") === "page",
      ),
    ).toBe(true);
  });

  it("toggles the sidebar collapse with aria-expanded", async () => {
    await renderShell();
    const collapse = screen.getByRole("button", {
      name: "Colapsar barra lateral",
    });
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(collapse);
    const expand = screen.getByRole("button", {
      name: "Expandir barra lateral",
    });
    expect(expand).toHaveAttribute("aria-expanded", "false");
  });

  it("renders the locale switcher in the topbar", async () => {
    await renderShell();
    // The locale control became a single action button on 2026-08-24, so there
    // is no longer a `role="group"` named «Idioma» — its accessible name now
    // states what pressing it does.
    expect(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    ).toBeInTheDocument();
    // And the theme control sits beside it, which is what this assertion is
    // really guarding: that the topbar's default `end` slot is mounted.
    expect(screen.getByRole("group", { name: "Tema" })).toBeInTheDocument();
  });

  it("opens the More sheet, closes on Escape and returns focus to the trigger", async () => {
    await renderShell();
    const more = screen.getByRole("button", { name: "Más" });
    expect(more).toHaveAttribute("aria-expanded", "false");

    more.focus();
    fireEvent.click(more);

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("link", { name: "Precios" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(more).toHaveFocus());
  });

  it("has no axe violations (responsive landmark duplication excluded — see D6)", async () => {
    const { container } = await renderShell();
    const violations = await getA11yViolations(container, ["landmark-unique"]);
    expect(violations).toEqual([]);
  });

  it("keeps the locale out of the UI store (D7)", async () => {
    await renderShell();
    expect(Object.keys(useShellUiStore.getState())).not.toContain("locale");
  });
});
