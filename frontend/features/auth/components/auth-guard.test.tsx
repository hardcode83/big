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
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ status: mocks.status }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => ({ replace: mocks.replace }),
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
});
