import { fireEvent, render, screen, waitFor } from "@/test/render";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { LoginForm } from "./login-form";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  clearSessionPresent: vi.fn(),
  // R4: a successful `login()` populates `user` via `/auth/me`, and the form
  // picks the destination from `user.role`. `null` makes the four legacy
  // "no role" assertions fall through to roleHome's default (`/dashboard`).
  user: null as null | { role: string },
  status: "anonymous" as
    | "anonymous"
    | "authenticated"
    | "loading"
    | "refreshing"
    | "expired",
  // The mock for `useSearchParams` returns a `URLSearchParams` built from
  // the test's URL — keeps the form's read of `?returnTo` and `?denied=role`
  // honest without a parallel mock.
  url: "/login?returnTo=%2Fdashboard",
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    login: mocks.login,
    status: mocks.status,
    user: mocks.user,
  }),
  clearSessionPresent: mocks.clearSessionPresent,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, refresh: mocks.refresh }),
  usePathname: () => "/login",
  useSearchParams: () => new URLSearchParams(new URL(mocks.url, "http://test").search),
}));

function renderForm() {
  return render(
    <I18nProvider locale="es">
      <LoginForm />
    </I18nProvider>,
  );
}

describe("LoginForm", () => {
  beforeEach(() => {
    mocks.login.mockReset();
    mocks.replace.mockReset();
    mocks.refresh.mockReset();
    mocks.clearSessionPresent.mockReset();
    mocks.user = null;
    mocks.status = "anonymous";
    mocks.url = "/login?returnTo=%2Fdashboard";
    window.history.replaceState({}, "", "/login?returnTo=%2Fdashboard");
    // The "purges cookie" test sets `autohostai.session.present` to "1" and
    // then to "" via `mockImplementation`; cleanup alone does not reset
    // `document.cookie` in jsdom, so the next test would otherwise inherit the
    // stale value. Clear it explicitly between tests.
    document.cookie =
      "autohostai.session.present=; path=/; max-age=0; samesite=lax";
  });

  it("submits localized credentials and navigates to a safe internal return path", async () => {
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith("user@example.com", "secret"));
    expect(mocks.replace).toHaveBeenCalledWith("/dashboard");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("uses the dashboard as the default destination without returnTo", async () => {
    window.history.replaceState({}, "", "/login");
    mocks.url = "/login";
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith("", ""));
    expect(mocks.replace).toHaveBeenCalledWith("/dashboard");
  });

  it.each([
    "/login?returnTo=https%3A%2F%2Fevil.example%2F",
    "/login?returnTo=%2F%2Fevil.example%2F",
    "/login?returnTo=%2F%5C%5Cevil.example",
  ])("falls back for an unsafe returnTo: %s", async (url) => {
    window.history.replaceState({}, "", url);
    mocks.url = url;
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith("", ""));
    expect(mocks.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("keeps the form and shows a localized error when login fails", async () => {
    mocks.login.mockRejectedValue(new Error("wrong credentials"));
    renderForm();

    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No se ha podido iniciar sesión. Inténtalo de nuevo.",
    );
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  // R2 #1 — CLEANER redirects to the welcome page (not directly to /cleaner);
  // the welcome page itself routes to /cleaner via roleHome().
  it("redirects a CLEANER to /welcome?role=CLEANER when no returnTo is present", async () => {
    window.history.replaceState({}, "", "/login");
    mocks.url = "/login";
    mocks.user = { role: "CLEANER" };
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalled());
    expect(mocks.replace).toHaveBeenCalledWith("/welcome?role=CLEANER");
  });

  it("redirects a TECHNICIAN to /welcome?role=TECHNICIAN when no returnTo is present", async () => {
    window.history.replaceState({}, "", "/login");
    mocks.url = "/login";
    mocks.user = { role: "TECHNICIAN" };
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalled());
    expect(mocks.replace).toHaveBeenCalledWith("/welcome?role=TECHNICIAN");
  });

  it("redirects a TENANT_OWNER directly to /dashboard (not via /welcome)", async () => {
    window.history.replaceState({}, "", "/login");
    mocks.url = "/login";
    mocks.user = { role: "TENANT_OWNER" };
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalled());
    expect(mocks.replace).toHaveBeenCalledWith("/dashboard");
  });

  // R5 — the «Volver a la landing» control is a button (not a link) so that
  // the order `clearSessionPresent → router.replace("/") → router.refresh()`
  // runs BEFORE the browser commits to the navigation. An `<a href="/">` would
  // let the native click handler race the React onClick and the cookie would
  // still be set when RootPage re-evaluates, sending the user right back into
  // the `/login → / → /dashboard → /login` loop (R5 #2).
  it("renders the back-to-landing control as a button with role='link'", () => {
    renderForm();
    const button = screen.getByRole("link", { name: /Volver a la landing/ });
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
    // The accessible name comes from the same `auth.backToLanding` key in
    // both locales.
    expect(button).toHaveAccessibleName("← Volver a la landing");
    expect(button).toHaveClass("tap-target");
  });

  it("invokes clearSessionPresent → router.replace('/') → router.refresh() in order on click", () => {
    renderForm();
    const calls: string[] = [];
    mocks.clearSessionPresent.mockImplementation(() => calls.push("clearSessionPresent"));
    mocks.refresh.mockImplementation(() => {
      calls.push("router.refresh");
      return undefined;
    });
    mocks.replace.mockImplementation((value: string) => {
      calls.push(`router.replace:${value}`);
      return undefined;
    });

    fireEvent.click(screen.getByRole("link", { name: /Volver a la landing/ }));

    expect(calls).toEqual([
      "clearSessionPresent",
      "router.replace:/",
      "router.refresh",
    ]);
  });

  it("purges the autohostai.session.present cookie as part of the back-to-landing click (R5 #5)", () => {
    // Seed the cookie as if a previous login had written it; the click should
    // make it disappear. `clearSessionPresent` (`lib/auth/session-presence-cookie.ts`)
    // writes `...; max-age=0` — the cookie remains in document.cookie as an
    // empty value, so we assert the call happened AND that no `1` survives.
    document.cookie = "autohostai.session.present=1; path=/";
    expect(document.cookie).toContain("autohostai.session.present=1");

    mocks.clearSessionPresent.mockImplementation(() => {
      // Simulate what the real helper does — empty value + max-age=0.
      document.cookie = "autohostai.session.present=; path=/; max-age=0";
    });

    renderForm();

    fireEvent.click(screen.getByRole("link", { name: /Volver a la landing/ }));

    expect(mocks.clearSessionPresent).toHaveBeenCalledTimes(1);
    expect(document.cookie).not.toContain("autohostai.session.present=1");
  });

  // R1 #5 — `AuthGuard` redirects here with `?denied=role`. The visitor is
  // already authenticated; the page surfaces `auth.deniedRole` for one render
  // and then resolves the shell via `roleHome(user.role)`.
  it("shows auth.deniedRole and redirects to roleHome when ?denied=role + authenticated", async () => {
    window.history.replaceState({}, "", "/login?returnTo=%2Fcleaner&denied=role");
    mocks.url = "/login?returnTo=%2Fcleaner&denied=role";
    mocks.status = "authenticated";
    mocks.user = { role: "CLEANER" };

    renderForm();

    // The alert should be visible before the useEffect dispatches the redirect.
    // `getByText` matches the rendered text directly — `getByRole("alert", {
    // name })` does not work for `<p role="alert">` in this jsdom version
    // (the accessible-name computation does not pick up text content for
    // `role="alert"`), so we read the text explicitly.
    expect(
      screen.getByText(/No tienes permiso para acceder a esa sección/),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(mocks.replace).toHaveBeenCalledWith("/cleaner"),
    );
  });

  it("does not auto-redirect ?denied=role when the visitor is not yet authenticated", () => {
    window.history.replaceState({}, "", "/login?denied=role");
    mocks.url = "/login?denied=role";
    mocks.status = "anonymous";

    renderForm();

    // No `deniedRole` alert (the visitor was sent here directly, not bounced).
    expect(
      screen.queryByText(/No tienes permiso para acceder a esa sección/),
    ).not.toBeInTheDocument();
    // And no redirect — the form stays put for them to authenticate.
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});