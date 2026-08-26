import { fireEvent, render, screen, waitFor } from "@/test/render";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { LoginForm } from "./login-form";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn(),
  // R4: a successful `login()` populates `user` via `/auth/me`, and the form
  // picks the destination from `user.role`. `null` makes the four legacy
  // "no role" assertions fall through to roleHome's default (`/dashboard`).
  user: null as null | { role: string },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ login: mocks.login, status: "anonymous", user: mocks.user }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  usePathname: () => "/login",
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
    mocks.user = null;
    window.history.replaceState({}, "", "/login?returnTo=%2Fdashboard");
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

  // R4 — login without `?returnTo=` picks the shell from the role returned by
  // `/auth/me` (already cached on `user` by the AuthProvider).
  it("redirects a CLEANER to /cleaner when no returnTo is present", async () => {
    window.history.replaceState({}, "", "/login");
    mocks.user = { role: "CLEANER" };
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalled());
    expect(mocks.replace).toHaveBeenCalledWith("/cleaner");
  });

  it("redirects a TECHNICIAN to /tech when no returnTo is present", async () => {
    window.history.replaceState({}, "", "/login");
    mocks.user = { role: "TECHNICIAN" };
    mocks.login.mockResolvedValue(undefined);
    renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalled());
    expect(mocks.replace).toHaveBeenCalledWith("/tech");
  });

  // R2 — a visible back-link under the submit button takes the visitor back
  // to the landing without going through the browser back button.
  it("renders a back-link to the landing below the submit button", () => {
    renderForm();
    const link = screen.getByRole("link", { name: /Volver a la landing/ });
    expect(link).toHaveAttribute("href", "/");
    // 44×44 touch target — same primitive guarantee the rest of the chrome uses.
    expect(link).toHaveClass("tap-target");
  });
});
