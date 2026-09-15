import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { OwnerStatement, OwnerStatementDetail } from "../data";
import { StatementsPage } from "./statements-page";

const useStatementsList = vi.hoisted(() => vi.fn());
const useStatementDetail = vi.hoisted(() => vi.fn());
const useStatementPropertyDirectory = vi.hoisted(() => vi.fn());
const authUser = vi.hoisted(() => ({
  current: { tenant_id: "tenant-1" } as { tenant_id: string } | null,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: authUser.current }),
}));

vi.mock("../hooks/use-statements-data", () => ({
  useStatementsList,
  useStatementDetail,
  useStatementPropertyDirectory,
}));

const STATEMENTS: OwnerStatement[] = [
  {
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
  },
];

const DETAIL: OwnerStatementDetail = {
  ...STATEMENTS[0]!,
  reservations: [],
  expenses: [],
};

function directory() {
  return {
    index: new Map([["p-1", { name: "Ático Sol" }]]),
    isPending: false,
    data: { data: [{ id: "p-1", name: "Ático Sol" }] },
  };
}

function emptyListPage() {
  return {
    isPending: false,
    isFetching: false,
    isError: false,
    data: { items: [], total: 0, page: 1, perPage: 20 },
    refetch: vi.fn(),
  };
}

function filledListPage() {
  return {
    isPending: false,
    isFetching: false,
    isError: false,
    data: { items: STATEMENTS, total: 1, page: 1, perPage: 20 },
    refetch: vi.fn(),
  };
}

function detailPage(state: { kind: "loading" } | { kind: "ok"; data: OwnerStatement }) {
  return state;
}

function renderPage() {
  return render(
    <I18nProvider locale="es">
      <StatementsPage />
    </I18nProvider>,
  );
}

describe("StatementsPage — the /statements entry view (task 6.3)", () => {
  it("renders the listing when no statement is selected", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(emptyListPage());
    useStatementPropertyDirectory.mockReturnValue(directory());
    useStatementDetail.mockReturnValue(detailPage({ kind: "loading" }));

    renderPage();

    // The list view's title is present; the detail view's "back to list"
    // control is NOT (only the detail view mounts it).
    expect(screen.getByRole("heading", { name: "Liquidaciones" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "« Volver al listado »" }),
    ).not.toBeInTheDocument();
  });

  it("swaps the listing for the detail when a row is selected, and returns to the list via onBack", () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(filledListPage());
    useStatementPropertyDirectory.mockReturnValue(directory());
    // `useStatementDetail` is enabled by `statementId !== null`. We start
    // the mock in the loading state (statementId is null on first render)
    // and flip it to "ok" with the row's data the moment the parent has
    // selected an id. The `mockImplementation` reads the call args so the
    // orchestrator's state transitions are observable through the mock.
    useStatementDetail.mockImplementation((statementId: string | null) => {
      if (!statementId) {
        return { isPending: true, isError: false, data: undefined };
      }
      return {
        isPending: false,
        isError: false,
        data: { ...DETAIL, id: statementId },
      };
    });

    renderPage();

    // List shows the row, with the resolved property name. Selecting it
    // routes to the detail branch.
    const row = screen.getByRole("button", { name: /Ático Sol/ });
    fireEvent.click(row);

    // After clicking, the detail branch mounts — its back-to-list button
    // is the canonical signal that we are in the detail view (the listing
    // branch never renders it).
    expect(
      screen.getByRole("button", { name: "« Volver al listado »" }),
    ).toBeInTheDocument();
    // The listing title is gone — the orchestrator swapped the branches.
    expect(
      screen.queryByRole("heading", { name: "Liquidaciones" }),
    ).not.toBeInTheDocument();

    // onBack returns us to the listing.
    fireEvent.click(screen.getByRole("button", { name: "« Volver al listado »" }));
    expect(screen.getByRole("heading", { name: "Liquidaciones" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "« Volver al listado »" }),
    ).not.toBeInTheDocument();
  });
});

describe("StatementsPage — accessibility", () => {
  it("has no accessibility violations on the listing branch", async () => {
    authUser.current = { tenant_id: "tenant-1" };
    useStatementsList.mockReturnValue(filledListPage());
    useStatementPropertyDirectory.mockReturnValue(directory());
    useStatementDetail.mockReturnValue(detailPage({ kind: "loading" }));

    const { container } = renderPage();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
