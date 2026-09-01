import { beforeEach, describe, expect, it, vi } from "vitest";

import { getA11yViolations, render, screen } from "@/test/render";
import { QueryProvider } from "@/lib/query/query-provider";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { CleanerShell } from "@/features/shell/components/cleaner-shell";
import { TechnicianShell } from "@/features/shell/components/technician-shell";
import { PublicShell } from "@/features/shell/components/public-shell";
import { GuestShell } from "@/features/shell/components/guest-shell";

const nav = vi.hoisted(() => ({ pathname: "/cleaner" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  // The cleaner/technician tops include the LocaleSwitcher (which now calls
  // router.refresh() after writing the cookie). The tests never trigger the
  // switcher, so a stable no-op spy is enough.
  useRouter: () => ({ refresh: vi.fn() }),
}));
// Cleaner/technician tops now include the UserMenu (public-zone-hardening
// R3/D2), which calls `useAuth()` to render the email trigger. The shell
// tests do not exercise the menu itself, so a stub user is enough.
// `NotificationBell` (`notifications-inbox-web` R3.1) needs `status` and `user` both resolved
// (design D16), so the stub gained them. `PublicShell` and `GuestShell` do not mount the bell
// at all, which is what the tests below pin — not that the stub happens to be empty.
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    status: "authenticated",
    user: { tenant_id: "t1", id: "u1", email: "field@example.com" },
    logout: vi.fn(),
  }),
  getSessionGeneration: () => 1,
}));
// UserMenu now consumes useLogoutMutation, which calls useRuntimeConfig for
// the API base URL. The shell tests don't exercise the menu, so a stub
// config keeps the import graph intact.
vi.mock("@/lib/config/runtime-config-provider", () => ({
  useRuntimeConfig: () => ({ apiBaseUrl: "" }),
}));
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
  return render(
    <QueryProvider>
      <I18nProvider locale="es">{node}</I18nProvider>
    </QueryProvider>,
  );
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

describe("version badge placement (change app-version-visibility, R2.2/R2.6)", () => {
  it("shows the badge on the login shell, where there is no session yet", async () => {
    // R2.2: this is the surface that matters most for diagnosis — if the app is broken
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
    // R2.6: `/guest/[token]` is a surface for people outside the operation. The build
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

describe("the bell is in the authenticated shells and nowhere else (`notifications-inbox-web` R3.1)", () => {
  it("mounts it in CleanerShell", async () => {
    await renderShell(await CleanerShell({ children: <div>contenido</div> }));

    expect(
      screen.getByRole("button", { name: /Notificaciones/ }),
    ).toBeInTheDocument();
  });

  it("mounts it in TechnicianShell", async () => {
    await renderShell(await TechnicianShell({ children: <div>contenido</div> }));

    expect(
      screen.getByRole("button", { name: /Notificaciones/ }),
    ).toBeInTheDocument();
  });

  it("never mounts it in PublicShell, which carries no JWT (R3.1)", async () => {
    await renderShell(await PublicShell({ children: <div>contenido</div> }));

    expect(
      screen.queryByRole("button", { name: /Notificaciones/ }),
    ).not.toBeInTheDocument();
  });

  it("never mounts it in GuestShell, whose credential is a path token (R3.1)", async () => {
    await renderShell(await GuestShell({ children: <div>contenido</div> }));

    expect(
      screen.queryByRole("button", { name: /Notificaciones/ }),
    ).not.toBeInTheDocument();
  });
});
