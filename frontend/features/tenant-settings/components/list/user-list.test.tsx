import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, within } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

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

/**
 * A tenant whose directory does not fit in one `per_page` of 20 — the case
 * R1.1's "listado paginado" is about, and the one the first round of this
 * component could not reach at all: 42 users over three pages.
 */
const MULTI_PAGE = { ...PAGE, total: 42, page: 1, perPage: 20, totalPages: 3 };

function renderList() {
  return render(<UserList />, {
    wrapper: ({ children }) => <I18nProvider locale="es">{children}</I18nProvider>,
  });
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
    expect(screen.getByText("No se encontraron usuarios")).toBeInTheDocument();
  });

  it("shows the error state with a working retry", () => {
    const refetch = vi.fn();
    useUsersMock.mockReturnValue({ isPending: false, isError: true, data: undefined, refetch });
    renderList();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("renders a populated page's rows (name, email, role, status)", () => {
    useUsersMock.mockReturnValue({ isPending: false, isError: false, data: PAGE, refetch: vi.fn() });
    renderList();
    const table = within(screen.getByRole("table"));
    expect(table.getByText("Ana Owner")).toBeInTheDocument();
    expect(table.getByText("ana@example.com")).toBeInTheDocument();
    expect(table.getByText("Propietaria")).toBeInTheDocument();
    expect(table.getByText("Activo")).toBeInTheDocument();
    expect(table.getByRole("button", { name: "Ver" })).toBeInTheDocument();
  });

  it("passes role/status filters to useUsers as query params (R1.2)", () => {
    useUsersMock.mockReturnValue({ isPending: false, isError: false, data: PAGE, refetch: vi.fn() });
    renderList();

    fireEvent.change(screen.getByLabelText("Rol"), { target: { value: "CLEANER" } });
    expect(useUsersMock).toHaveBeenLastCalledWith({ page: 1, role: "CLEANER" });

    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "SUSPENDED" } });
    expect(useUsersMock).toHaveBeenLastCalledWith({
      page: 1,
      role: "CLEANER",
      status: "SUSPENDED",
    });
  });

  it("keeps a natural keyboard focus order: role/status filters, then the row's View button", () => {
    useUsersMock.mockReturnValue({ isPending: false, isError: false, data: PAGE, refetch: vi.fn() });
    renderList();

    const controls = [
      screen.getByLabelText("Rol"),
      screen.getByLabelText("Estado"),
      screen.getByRole("button", { name: "Limpiar filtros" }),
      screen.getByRole("button", { name: "Ver" }),
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

  /**
   * R1.1's "listado paginado". Round 1 of this component sent no `page` at
   * all and rendered no page controls, so a tenant with more than one page of
   * users could not reach row 21 from this screen. These cases pin the whole
   * loop — the control is there, it moves, it re-asks the hook with the new
   * page, and it stops at both ends.
   *
   * The mock answers the `page` it was asked for, the way the backend does:
   * without that, "next" would look like it worked while the view stayed on
   * page 1 forever.
   */
  describe("pagination (R1.1)", () => {
    function mockPagedUsers(envelope = MULTI_PAGE) {
      useUsersMock.mockImplementation((filters: { page?: number } = {}) => ({
        isPending: false,
        isError: false,
        data: { ...envelope, page: filters.page ?? 1 },
        refetch: vi.fn(),
      }));
    }

    it("asks for page 1 on first render", () => {
      mockPagedUsers();
      renderList();
      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 1 });
    });

    it("renders the page controls when the directory spans more than one page", () => {
      mockPagedUsers();
      renderList();

      const nav = within(screen.getByRole("navigation", { name: "Paginación de usuarios" }));
      expect(nav.getByText(/Página 1 de 3/)).toBeInTheDocument();
      expect(nav.getByText(/42 usuarios en total/)).toBeInTheDocument();
      expect(nav.getByRole("button", { name: "Página anterior" })).toBeInTheDocument();
      expect(nav.getByRole("button", { name: "Página siguiente" })).toBeInTheDocument();
    });

    it("disables 'previous' on the first page", () => {
      mockPagedUsers();
      renderList();
      expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Página siguiente" })).toBeEnabled();
    });

    it("advances the page on 'next' and re-asks useUsers with the new page param", () => {
      mockPagedUsers();
      renderList();
      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 1 });

      fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));

      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 2 });
      expect(screen.getByText(/Página 2 de 3/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Página anterior" })).toBeEnabled();
    });

    it("goes back on 'previous'", () => {
      mockPagedUsers();
      renderList();

      fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 2 });

      fireEvent.click(screen.getByRole("button", { name: "Página anterior" }));
      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 1 });
      expect(screen.getByText(/Página 1 de 3/)).toBeInTheDocument();
    });

    it("disables 'next' on the last page", () => {
      mockPagedUsers();
      renderList();

      fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
      fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));

      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 3 });
      expect(screen.getByText(/Página 3 de 3/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Página siguiente" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Página anterior" })).toBeEnabled();
    });

    it("keeps both ends disabled when everything fits in one page", () => {
      mockPagedUsers({ ...PAGE, total: 1, totalPages: 1 });
      renderList();

      expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Página siguiente" })).toBeDisabled();
    });

    it("returns to page 1 when a filter changes, so the new filter never lands on a page that no longer exists", () => {
      mockPagedUsers();
      renderList();

      fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 2 });

      fireEvent.change(screen.getByLabelText("Rol"), { target: { value: "CLEANER" } });
      expect(useUsersMock).toHaveBeenLastCalledWith({ page: 1, role: "CLEANER" });
    });
  });
});
