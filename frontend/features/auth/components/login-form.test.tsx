import { fireEvent, render, screen, waitFor } from "@/test/render";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { LoginForm } from "./login-form";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ login: mocks.login, status: "anonymous" }),
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
});
