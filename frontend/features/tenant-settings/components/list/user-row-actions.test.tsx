import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

const useAuthMock = vi.hoisted(() => vi.fn());
const useHasPermissionMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({
  useAuth: useAuthMock,
  useHasPermission: useHasPermissionMock,
}));

vi.mock("../detail/user-detail-view", () => ({
  UserDetailView: ({ userId }: { userId: string }) => (
    <div data-testid="user-detail-view">detail:{userId}</div>
  ),
}));
vi.mock("../detail/edit-user-form", () => ({
  EditUserForm: ({ userId }: { userId: string }) => (
    <div data-testid="edit-user-form">edit:{userId}</div>
  ),
}));
vi.mock("../detail/deactivate-user-confirm", () => ({
  DeactivateUserConfirm: ({ open }: { open: boolean }) =>
    open ? <div data-testid="deactivate-confirm" /> : null,
}));
vi.mock("../detail/reset-password-confirm", () => ({
  ResetPasswordConfirm: ({ open }: { open: boolean }) =>
    open ? <div data-testid="reset-password-confirm" /> : null,
}));

import { UserRowActions } from "./user-row-actions";
import type { UserDto } from "../../dto";

const USER: UserDto = {
  id: "user-1",
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

function renderRowActions(user: UserDto = USER) {
  return render(<UserRowActions user={user} />, {
    wrapper: ({ children }) => <I18nProvider locale="es">{children}</I18nProvider>,
  });
}

describe("UserRowActions (R1.3, R3, R4, design D4, D5)", () => {
  beforeEach(() => {
    useAuthMock.mockReturnValue({ user: { id: "owner-1", role: "TENANT_OWNER" } });
  });

  it("opens the read-only detail view for any row, regardless of permission", () => {
    useHasPermissionMock.mockReturnValue(false);
    renderRowActions();
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));
    expect(screen.getByTestId("user-detail-view")).toBeInTheDocument();
  });

  it("for a PROPERTY_MANAGER session (no MANAGE_USERS) hosts only the read-only view, never the mutation forms", () => {
    useHasPermissionMock.mockReturnValue(false);
    renderRowActions();
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));

    expect(screen.getByTestId("user-detail-view")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restablecer contraseña" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desactivar" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("deactivate-confirm")).not.toBeInTheDocument();
    expect(screen.queryByTestId("reset-password-confirm")).not.toBeInTheDocument();
  });

  it("with MANAGE_USERS shows edit/reset/deactivate controls alongside the detail view", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderRowActions();
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));

    expect(screen.getByRole("button", { name: "Editar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restablecer contraseña" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desactivar" })).toBeInTheDocument();
  });

  it("switches the Sheet to EditUserForm when Edit is clicked", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderRowActions();
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));
    fireEvent.click(screen.getByRole("button", { name: "Editar" }));

    expect(screen.getByTestId("edit-user-form")).toBeInTheDocument();
    expect(screen.queryByTestId("user-detail-view")).not.toBeInTheDocument();
  });

  it("does not offer Deactivate for an already-INACTIVE row", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderRowActions({ ...USER, status: "INACTIVE" });
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));
    expect(screen.queryByRole("button", { name: "Desactivar" })).not.toBeInTheDocument();
  });

  it("keeps a natural keyboard focus order: View, then Edit / Reset password / Deactivate", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderRowActions();

    const view = screen.getByRole("button", { name: "Ver" });
    expect(view.tabIndex).toBeGreaterThanOrEqual(0);
    view.focus();
    expect(view).toHaveFocus();

    fireEvent.click(view);
    const actions = [
      screen.getByRole("button", { name: "Editar" }),
      screen.getByRole("button", { name: "Restablecer contraseña" }),
      screen.getByRole("button", { name: "Desactivar" }),
    ];

    for (const control of actions) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(control).toHaveFocus();
    }

    // The three actions keep the order they are announced in, so tabbing
    // inside the Sheet walks edit → reset → deactivate.
    for (let i = 0; i < actions.length - 1; i += 1) {
      expect(
        actions[i].compareDocumentPosition(actions[i + 1]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it("disables Deactivate for the acting user's own row", () => {
    useAuthMock.mockReturnValue({ user: { id: "user-1", role: "CLEANER" } });
    useHasPermissionMock.mockReturnValue(true);
    renderRowActions();
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));
    expect(screen.getByRole("button", { name: "Desactivar" })).toBeDisabled();
  });
});
