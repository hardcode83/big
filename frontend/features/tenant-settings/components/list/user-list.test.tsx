import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, within } from "@/test/render";

const useUsersMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-users", () => ({
  useUsers: useUsersMock,
}));

const useAuthMock = vi.hoisted(() => vi.fn());
const useHasPermissionMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({
  useAuth: useAuthMock,
  useHasPermission: useHasPermissionMock,
}));

import { UserList } from "./user-list";

const PAGE = {
  data: [
    {
      id: "user-1",
      name: "Ana Owner",
      email: "ana@example.com",
      phone: null,
      preferredLanguage: "es",
      role: "TENANT_OWNER",
      status: "ACTIVE",
      lastLoginAt: null,
      createdAt: "2026-08-01T09:00:00Z",
      updatedAt: "2026-08-01T09:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  perPage: 20,
  totalPages: 1,
};

function renderList() {
  return render(<UserList />);
}

describe("UserList (R1.1, R1.2, R1.3)", () => {
  beforeEach(() => {
    useAuthMock.mockReturnValue({ user: { id: "user-1", role: "TENANT_OWNER" } });
    useHasPermissionMock.mockReturnValue(true);
  });

  it("shows the loading state", () => {
    useUsersMock.mockReturnValue({ isPending: true, isError: false, data: undefined, refetch: vi.fn() });
    renderList();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the empty state when the page has no rows", () => {
    useUsersMock.mockReturnValue({
      isPending: false,
      isError: false,
      data: { ...PAGE, data: [], total: 0, totalPages: 0 },
      refetch: vi.fn(),
    });
    renderList();
    expect(screen.getByText("No users found")).toBeInTheDocument();
  });

  it("shows the error state with a working retry", () => {
    const refetch = vi.fn();
    useUsersMock.mockReturnValue({ isPending: false, isError: true, data: undefined, refetch });
    renderList();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders a populated page's rows (name, email, role, status)", () => {
    useUsersMock.mockReturnValue({ isPending: false, isError: false, data: PAGE, refetch: vi.fn() });
    renderList();
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Ana Owner")).toBeInTheDocument();
    expect(table.getByText("ana@example.com")).toBeInTheDocument();
    expect(table.getByText("TENANT_OWNER")).toBeInTheDocument();
    expect(table.getByText("ACTIVE")).toBeInTheDocument();
    expect(table.getByRole("button", { name: "View" })).toBeInTheDocument();
  });

  it("passes role/status filters to useUsers as query params (R1.2)", () => {
    useUsersMock.mockReturnValue({ isPending: false, isError: false, data: PAGE, refetch: vi.fn() });
    renderList();

    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "CLEANER" } });
    expect(useUsersMock).toHaveBeenLastCalledWith({ role: "CLEANER" });

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "SUSPENDED" } });
    expect(useUsersMock).toHaveBeenLastCalledWith({ role: "CLEANER", status: "SUSPENDED" });
  });

  it("keeps a natural keyboard focus order: role/status filters, then the row's View button", () => {
    useUsersMock.mockReturnValue({ isPending: false, isError: false, data: PAGE, refetch: vi.fn() });
    renderList();

    const controls = [
      screen.getByLabelText("Role"),
      screen.getByLabelText("Status"),
      screen.getByRole("button", { name: "Clear filters" }),
      screen.getByRole("button", { name: "View" }),
    ];

    for (const control of controls) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(control).toHaveFocus();
    }

    // No control opts out of, or reorders, the natural tab sequence: each one
    // still precedes the next in document order, so tabbing walks filters →
    // row action rather than jumping back up the page.
    for (let i = 0; i < controls.length - 1; i += 1) {
      expect(
        controls[i].compareDocumentPosition(controls[i + 1]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });
});
