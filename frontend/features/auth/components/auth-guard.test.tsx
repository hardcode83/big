import { act, render, screen, waitFor } from "@/test/render";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { AuthGuard } from "./auth-guard";

const mocks = vi.hoisted(() => ({
  pathname: "/dashboard",
  replace: vi.fn(),
  status: "anonymous" as
    | "anonymous"
    | "authenticated"
    | "loading"
    | "refreshing"
    | "expired",
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

function renderGuard() {
  return render(
    <I18nProvider locale="es">
      <AuthGuard>
        <span>protected content</span>
      </AuthGuard>
    </I18nProvider>,
  );
}

describe("AuthGuard", () => {
  beforeEach(() => {
    mocks.status = "anonymous";
    mocks.pathname = "/dashboard";
    mocks.replace.mockReset();
    window.history.replaceState({}, "", "/dashboard");
  });

  it("redirects anonymous users to login with an internal return path", async () => {
    renderGuard();

    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith(
        "/login?returnTo=%2Fdashboard",
      ),
    );
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("renders protected content only for authenticated users", () => {
    mocks.status = "authenticated";

    renderGuard();

    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("renders a localized busy state while auth is loading", () => {
    mocks.status = "loading";

    renderGuard();

    expect(screen.getByRole("status")).toHaveTextContent("Comprobando sesión…");
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("renders a localized refresh state while auth is refreshing", () => {
    mocks.status = "refreshing";

    renderGuard();

    expect(screen.getByRole("status")).toHaveTextContent("Renovando sesión…");
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("shows the localized expiration state before redirecting", async () => {
    mocks.status = "expired";

    renderGuard();

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Tu sesión ha caducado. Inicia sesión de nuevo.",
    );
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith(
      "/login?returnTo=%2Fdashboard",
    ));
  });

  it("preserves query string and fragment in a safe internal return path", async () => {
    mocks.pathname = "/properties/42";
    window.history.replaceState({}, "", "/properties/42?tab=timeline#details");

    renderGuard();

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith(
      "/login?returnTo=%2Fproperties%2F42%3Ftab%3Dtimeline%23details",
    ));
  });

  it("redirects once when an authenticated user becomes anonymous after logout", async () => {
    mocks.status = "authenticated";
    const view = renderGuard();

    mocks.status = "anonymous";
    await act(async () => view.rerender(
      <I18nProvider locale="es">
        <AuthGuard>
          <span>protected content</span>
        </AuthGuard>
      </I18nProvider>,
    ));

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledOnce());
    expect(mocks.replace).toHaveBeenCalledWith("/login?returnTo=%2Fdashboard");
  });

  describe("allow prop (R1)", () => {
    beforeEach(() => {
      mocks.status = "authenticated";
      mocks.user = {
        id: "user-1",
        role: "CLEANER",
        tenant_id: "tenant-1",
      };
      window.history.replaceState({}, "", "/cleaner");
      mocks.pathname = "/cleaner";
      mocks.replace.mockReset();
    });

    function renderWithAllow(
      allow: readonly ("CLEANER" | "TECHNICIAN" | "TENANT_OWNER" | "PROPERTY_MANAGER" | "SUPER_ADMIN")[],
    ) {
      return render(
        <I18nProvider locale="es">
          <AuthGuard allow={allow}>
            <span>protected content</span>
          </AuthGuard>
        </I18nProvider>,
      );
    }

    it("renders children when user.role is in allow", () => {
      renderWithAllow(["CLEANER"]);

      expect(screen.getByText("protected content")).toBeInTheDocument();
      expect(mocks.replace).not.toHaveBeenCalled();
    });

    it("redirects to /login?denied=role when user.role is not in allow", async () => {
      mocks.user = {
        id: "user-2",
        role: "TENANT_OWNER",
        tenant_id: "tenant-1",
      };

      renderWithAllow(["CLEANER"]);

      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
      await waitFor(() =>
        expect(mocks.replace).toHaveBeenCalledWith(
          "/login?returnTo=%2Fcleaner&denied=role",
        ),
      );
      // The `redirecting` ref must de-duplicate: the same mount under
      // React.StrictMode must not fire `router.replace` twice (QA finding 1).
      expect(mocks.replace).toHaveBeenCalledTimes(1);
    });

    it("does not evaluate allow for anonymous users", async () => {
      mocks.status = "anonymous";
      mocks.user = null;

      renderWithAllow(["CLEANER"]);

      await waitFor(() =>
        expect(mocks.replace).toHaveBeenCalledWith(
          "/login?returnTo=%2Fcleaner",
        ),
      );
      expect(mocks.replace).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    });
  });
});
