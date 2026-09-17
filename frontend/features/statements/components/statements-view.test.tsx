import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen } from "@/test/render";

import { StatementsView } from "./statements-view";

const useStatementsList = vi.hoisted(() => vi.fn());
const useStatementPropertyDirectory = vi.hoisted(() => vi.fn());
const authUser = vi.hoisted(() => ({ current: { tenant_id: "tenant-1" } as { tenant_id: string } | null }));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: authUser.current }),
}));

vi.mock("../hooks/use-statements-data", () => ({
  useStatementsList,
  useStatementPropertyDirectory,
}));

function emptyPage(page = 1) {
  return { isPending: false, isError: false, data: { items: [], total: 0, page, perPage: 20 } };
}

function renderView() {
  return render(
    <I18nProvider locale="es">
      <StatementsView />
    </I18nProvider>,
  );
}

describe("StatementsView — local, view-scoped filters/page state (design D5, task 3.1)", () => {
  it("renders the title and an initial, empty filter/page-1 query", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(emptyPage());
    useStatementPropertyDirectory.mockReturnValue({ index: new Map(), isPending: false, data: undefined });
    renderView();
    expect(screen.getByRole("heading", { name: "Liquidaciones" })).toBeInTheDocument();
    expect(useStatementsList).toHaveBeenCalledWith({}, 1);
  });

  it("selecting a status filter resets the page to 1 and never sends a tenant_id", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(emptyPage());
    useStatementPropertyDirectory.mockReturnValue({ index: new Map(), isPending: false, data: undefined });
    renderView();

    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "SENT" } });

    const lastCall = useStatementsList.mock.calls.at(-1);
    expect(lastCall).toEqual([{ status: "SENT" }, 1]);
    expect(lastCall?.[0]).not.toHaveProperty("tenant_id");
  });

  it("moving to the next page keeps the current filters", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [], total: 45, page: 1, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue({ index: new Map(), isPending: false, data: undefined });
    renderView();

    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "SENT" } });
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));

    const lastCall = useStatementsList.mock.calls.at(-1);
    expect(lastCall).toEqual([{ status: "SENT" }, 2]);
  });
});

describe("StatementsView — resets local state when the tenant changes (security.md rule 1, R1.3)", () => {
  it("clears filters and returns to page 1 after a tenant switch", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(emptyPage());
    useStatementPropertyDirectory.mockReturnValue({ index: new Map(), isPending: false, data: undefined });
    const { rerender } = renderView();

    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "SENT" } });
    expect(useStatementsList.mock.calls.at(-1)).toEqual([{ status: "SENT" }, 1]);

    authUser.current = { tenant_id: "tenant-2" };
    rerender(
      <I18nProvider locale="es">
        <StatementsView />
      </I18nProvider>,
    );

    expect(useStatementsList.mock.calls.at(-1)).toEqual([{}, 1]);
  });

  it("does not reset on a re-render that keeps the same tenant", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(emptyPage());
    useStatementPropertyDirectory.mockReturnValue({ index: new Map(), isPending: false, data: undefined });
    const { rerender } = renderView();

    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "SENT" } });
    rerender(
      <I18nProvider locale="es">
        <StatementsView />
      </I18nProvider>,
    );

    expect(useStatementsList.mock.calls.at(-1)).toEqual([{ status: "SENT" }, 1]);
  });
});
