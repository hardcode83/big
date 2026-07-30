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
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
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
    expect(screen.getByRole("group", { name: "Idioma" })).toBeInTheDocument();
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
