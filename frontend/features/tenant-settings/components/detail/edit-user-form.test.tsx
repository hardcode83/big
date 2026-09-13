import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

const useUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-user", () => ({ useUser: useUserMock }));

const useUpdateUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-update-user", () => ({ useUpdateUser: useUpdateUserMock }));

const useAuthMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ useAuth: useAuthMock }));

import { EditUserForm } from "./edit-user-form";

const USER = {
  id: "user-2",
  name: "Marta Cleaner",
  email: "marta@example.com",
  phone: null,
  preferredLanguage: "es",
  role: "CLEANER",
  status: "ACTIVE",
  lastLoginAt: null,
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
};

function renderForm(userId = "user-2") {
  return render(<EditUserForm userId={userId} />, {
    wrapper: ({ children }) => <I18nProvider locale="es">{children}</I18nProvider>,
  });
}

describe("EditUserForm (R3.1, R3.2, R3.3)", () => {
  const mutate = vi.fn();

  beforeEach(() => {
    mutate.mockReset();
    useUserMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: USER,
      refetch: vi.fn(),
    });
    useUpdateUserMock.mockReturnValue({ mutate, isPending: false, isError: false });
    useAuthMock.mockReturnValue({ user: { id: "owner-1", role: "TENANT_OWNER" } });
  });

  it("sends only the changed fields on submit (R3.1)", () => {
    renderForm();
    fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Marta C." } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    expect(mutate).toHaveBeenCalledWith(
      { userId: "user-2", input: { name: "Marta C." } },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("disables the role and status controls when the target row is the acting user's own (R3.3)", () => {
    useAuthMock.mockReturnValue({ user: { id: "user-2", role: "CLEANER" } });
    renderForm();

    expect(screen.getByLabelText("Rol")).toBeDisabled();
    expect(screen.getByLabelText("Estado")).toBeDisabled();
  });

  it("leaves role/status enabled for a row that is not the acting user's own", () => {
    renderForm();
    expect(screen.getByLabelText("Rol")).not.toBeDisabled();
    expect(screen.getByLabelText("Estado")).not.toBeDisabled();
  });

  it("disables the submit button while the mutation is pending", () => {
    useUpdateUserMock.mockReturnValue({ mutate, isPending: true, isError: false });
    renderForm();
    expect(screen.getByRole("button", { name: "Guardando…" })).toBeDisabled();
  });

  it("keeps a natural keyboard focus order: full name first, submit button reachable", () => {
    renderForm();
    const fullName = screen.getByLabelText("Nombre completo");
    fullName.focus();
    expect(fullName).toHaveFocus();

    const submit = screen.getByRole("button", { name: "Guardar cambios" });
    expect(submit.tabIndex).toBeGreaterThanOrEqual(0);
    submit.focus();
    expect(submit).toHaveFocus();
  });

  it("surfaces the backend's 422 (last-owner / self-action) with the backend's own message, no generic fallback (R3.2)", () => {
    useUpdateUserMock.mockReturnValue({
      mutate,
      isPending: false,
      isError: true,
      error: new ApiError({
        code: "VALIDATION_ERROR",
        message: "This would leave the tenant without an active owner, and there is no endpoint to appoint one from outside it",
        status: 422,
        details: {},
      }),
    });
    renderForm();

    expect(
      screen.getByText(
        "This would leave the tenant without an active owner, and there is no endpoint to appoint one from outside it",
      ),
    ).toBeInTheDocument();
  });
});
