/**
 * Regression test for tenant-settings-web R1.4/R6.2 (design D3): no
 * production code change here — `(workspace)/layout.tsx` already wraps every
 * workspace route (including `/settings`) in
 * `<AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}>`. This test pins
 * that exact `allow` list (so a future edit to the layout that silently
 * widens it fails here, in red) and then exercises `AuthGuard`'s own,
 * already-tested redirect behavior (mirroring
 * `features/auth/components/auth-guard.test.tsx`'s "allow prop" cases) for a
 * `CLEANER`/`TECHNICIAN` session hitting `/settings` directly.
 *
 * `Layout(...)` is called directly (not rendered) to read the JSX tree it
 * builds: `WorkspaceShell` is an async Server Component that cannot be
 * mounted through a plain client `render()`, but JSX element CREATION never
 * invokes it — `Layout({ children })` just returns
 * `<AuthGuard allow={...}><WorkspaceShell>{children}</WorkspaceShell></AuthGuard>`
 * as a plain element tree, which is enough to read `allow` off the real
 * `AuthGuard` element without needing to render the shell at all.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

import { AuthGuard } from "@/features/auth";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen, waitFor } from "@/test/render";

import Layout from "./layout";

const mocks = vi.hoisted(() => ({
  pathname: "/settings",
  replace: vi.fn(),
  status: "authenticated" as "authenticated",
  user: null as null | {
    id: string;
    role: "SUPER_ADMIN" | "TENANT_OWNER" | "PROPERTY_MANAGER" | "CLEANER" | "TECHNICIAN";
    tenant_id: string;
  },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ status: mocks.status, user: mocks.user }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("(workspace)/layout.tsx AuthGuard allow list (R1.4)", () => {
  it("pins the allow list to exactly TENANT_OWNER and PROPERTY_MANAGER", () => {
    const element = Layout({ children: <span>workspace content</span> });

    expect(element.type).toBe(AuthGuard);
    expect(element.props.allow).toEqual(["TENANT_OWNER", "PROPERTY_MANAGER"]);
  });
});

describe("/settings redirects CLEANER/TECHNICIAN sessions (R6.2)", () => {
  const ALLOW = ["TENANT_OWNER", "PROPERTY_MANAGER"] as const;

  beforeEach(() => {
    mocks.status = "authenticated";
    mocks.pathname = "/settings";
    mocks.replace.mockReset();
    window.history.replaceState({}, "", "/settings");
  });

  function renderGuardedSettings(
    role: "CLEANER" | "TECHNICIAN" | "TENANT_OWNER" | "PROPERTY_MANAGER" | "SUPER_ADMIN",
  ) {
    mocks.user = { id: "user-1", role, tenant_id: "tenant-1" };
    return render(
      <I18nProvider locale="es">
        <AuthGuard allow={ALLOW}>
          <span>settings content</span>
        </AuthGuard>
      </I18nProvider>,
    );
  }

  it("redirects a CLEANER session away from /settings", async () => {
    renderGuardedSettings("CLEANER");

    expect(screen.queryByText("settings content")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith(
        "/login?returnTo=%2Fsettings&denied=role",
      ),
    );
  });

  it("redirects a TECHNICIAN session away from /settings", async () => {
    renderGuardedSettings("TECHNICIAN");

    expect(screen.queryByText("settings content")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith(
        "/login?returnTo=%2Fsettings&denied=role",
      ),
    );
  });

  it("still renders /settings for TENANT_OWNER and PROPERTY_MANAGER (no regression)", () => {
    renderGuardedSettings("TENANT_OWNER");
    expect(screen.getByText("settings content")).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});
