import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen, within } from "@/test/render";

import type { OwnerStatement } from "../data";
import { StatementsList, type StatementsListProps } from "./statements-list";

const useStatementsList = vi.hoisted(() => vi.fn());
const useStatementPropertyDirectory = vi.hoisted(() => vi.fn());

vi.mock("../hooks/use-statements-data", () => ({
  useStatementsList,
  useStatementPropertyDirectory,
}));

const STATEMENT: OwnerStatement = {
  id: "st-1",
  propertyId: "p-1",
  periodStart: "2026-01-01",
  periodEnd: "2026-01-31",
  status: "READY",
  grossRevenue: "1000.00",
  otaCommissions: "100.00",
  netRevenue: "900.00",
  cleaningCosts: "50.00",
  laundryCosts: "20.00",
  amenitiesCosts: "10.00",
  maintenanceCosts: "0.00",
  specialistCosts: "0.00",
  otherCosts: "0.00",
  platformFee: "30.00",
  netOwnerResult: "790.50",
  notes: null,
  createdAt: "2026-02-01T00:00:00Z",
  updatedAt: "2026-02-01T00:00:00Z",
};

function baseProps(overrides: Partial<StatementsListProps> = {}): StatementsListProps {
  return {
    filters: {},
    page: 1,
    onPropertyIdChange: vi.fn(),
    onPeriodStartFromChange: vi.fn(),
    onPeriodStartToChange: vi.fn(),
    onStatusChange: vi.fn(),
    onPageChange: vi.fn(),
    ...overrides,
  };
}

function renderList(overrides: Partial<StatementsListProps> = {}) {
  const props = baseProps(overrides);
  const result = render(
    <I18nProvider locale="es">
      <StatementsList {...props} />
    </I18nProvider>,
  );
  return { ...result, props };
}

function directory(entries: Array<[string, { name: string }]> = [["p-1", { name: "Ático Sol" }]]) {
  return {
    data: { data: entries.map(([id, v]) => ({ id, name: v.name })), total: entries.length },
    index: new Map(entries),
    isPending: false,
  };
}

describe("StatementsList — explicit states (R1.2, R2.1, R2.4, task 3.4)", () => {
  it("shows loading while the query is pending, no rows and no error", () => {
    useStatementsList.mockReturnValue({ isPending: true, isError: false });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Listado de liquidaciones" })).not.toBeInTheDocument();
  });

  it("shows the empty state distinct from an error when total is 0", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [], total: 0, page: 1, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList();
    expect(screen.getByText("Sin liquidaciones")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders rows and pagination on success", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [STATEMENT], total: 1, page: 1, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList();
    expect(screen.getByRole("heading", { name: /Ático Sol/ })).toBeInTheDocument();
    // A single page (total=1 <= perPage=20): the nav still renders (design
    // parity with reviews/pricing pagination), both controls disabled.
    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("button", { name: "Página anterior" })).toBeDisabled();
    expect(within(nav).getByRole("button", { name: "Página siguiente" })).toBeDisabled();
  });

  it("renders pagination once there is more than one page", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [STATEMENT], total: 45, page: 2, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList();
    expect(
      screen.getByRole("navigation", { name: "Paginación de liquidaciones" }),
    ).toBeInTheDocument();
  });

  it("never renders financial rows on a 403/error, distinguishing it from empty (R1.2)", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
      refetch: vi.fn(),
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No tienes permiso para ver estas liquidaciones.",
    );
    expect(screen.queryByText("790,50")).not.toBeInTheDocument();
    expect(screen.queryByText("Sin liquidaciones")).not.toBeInTheDocument();
  });

  it("shows the generic error copy for a non-403 failure", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER", message: "boom", status: 500 }),
      refetch: vi.fn(),
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No se pudieron cargar las liquidaciones. Vuelve a intentarlo.",
    );
  });
});

describe("StatementsList — filters use the full property directory, not the page (R2.2, D2)", () => {
  it("offers a directory property that is not present in the current page's items", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [STATEMENT], total: 1, page: 1, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(
      directory([
        ["p-1", { name: "Ático Sol" }],
        ["p-2", { name: "Loft Latina" }],
      ]),
    );
    renderList();
    const select = screen.getByLabelText("Vivienda");
    expect(select).toHaveTextContent("Loft Latina");
  });

  it("forwards only the selected property UUID and resets to page 1 via the parent callback", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [STATEMENT], total: 1, page: 1, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    const { props } = renderList({ page: 3 });
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    expect(props.onPropertyIdChange).toHaveBeenCalledWith("p-1");
  });

  it("queries with the filters and page the parent passed in, and no tenant_id", () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [], total: 0, page: 2, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    renderList({ filters: { status: "SENT" }, page: 2 });
    expect(useStatementsList).toHaveBeenCalledWith({ status: "SENT" }, 2);
  });
});

describe("StatementsList — accessibility", () => {
  it("has no violations on a successful render", async () => {
    useStatementsList.mockReturnValue({
      isPending: false,
      isError: false,
      data: { items: [STATEMENT], total: 45, page: 1, perPage: 20 },
    });
    useStatementPropertyDirectory.mockReturnValue(directory());
    const { container } = renderList();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
