import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

const useHasPermissionMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({
  useHasPermission: useHasPermissionMock,
}));

vi.mock("./list/user-list", () => ({
  UserList: () => <div data-testid="user-list" />,
}));
vi.mock("./tenant-config-form", () => ({
  TenantConfigForm: () => <div data-testid="tenant-config-form" />,
}));
vi.mock("./detail/create-user-form", () => ({
  CreateUserForm: () => <div data-testid="create-user-form" />,
}));

import { TenantSettingsView } from "./tenant-settings-view";

function renderView() {
  return render(<TenantSettingsView />, {
    wrapper: ({ children }) => <I18nProvider locale="es">{children}</I18nProvider>,
  });
}

describe("TenantSettingsView (R1-R6, design D4, D5)", () => {
  beforeEach(() => {
    useHasPermissionMock.mockReset();
  });

  it("hides the 'add user' trigger and Sheet for a PROPERTY_MANAGER session (no MANAGE_USERS)", () => {
    useHasPermissionMock.mockReturnValue(false);
    renderView();

    expect(screen.queryByRole("button", { name: "Añadir usuario" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("for a TENANT_OWNER session shows the 'add user' trigger, which opens CreateUserForm in a Sheet and can close it", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderView();

    const trigger = screen.getByRole("button", { name: "Añadir usuario" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("create-user-form")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("mounts both sections — Usuarios (UserList) and Tenant (TenantConfigForm)", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderView();

    expect(screen.getByRole("heading", { name: "Usuarios" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tenant" })).toBeInTheDocument();
    expect(screen.getByTestId("user-list")).toBeInTheDocument();
    expect(screen.getByTestId("tenant-config-form")).toBeInTheDocument();
  });

  it("keeps the 'add user' trigger keyboard-focusable", () => {
    useHasPermissionMock.mockReturnValue(true);
    renderView();

    const trigger = screen.getByRole("button", { name: "Añadir usuario" });
    expect(trigger.tabIndex).toBeGreaterThanOrEqual(0);
    trigger.focus();
    expect(trigger).toHaveFocus();
  });
});
