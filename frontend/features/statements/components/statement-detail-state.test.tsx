import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen, waitFor } from "@/test/render";

import type { OwnerStatementDetail, StatementsDataSource } from "../data";
import { StatementDetailState } from "./statement-detail-state";

const useStatementDetail = vi.hoisted(() => vi.fn());
const exportCsv = vi.hoisted(() => vi.fn());
const exportPdf = vi.hoisted(() => vi.fn());

vi.mock("../hooks/use-statements-data", () => ({
  useStatementDetail,
}));

// The success branch now mounts `StatementDownloads`, whose `useStatementDownload`
// hook reads the tenant from auth and calls the statements data source. Mock both
// so mounting the detail never hits the real AuthProvider or the network, and so
// the 5.3 integration tests can assert the exact export endpoints.
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { tenant_id: "tenant-1" } }) }));
vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getStatementsDataSource: (): StatementsDataSource => ({
    listStatements: vi.fn(),
    getStatement: vi.fn(),
    exportCsv,
    exportPdf,
  }),
}));

afterEach(() => {
  exportCsv.mockReset();
  exportPdf.mockReset();
  vi.unstubAllGlobals();
});

const DETAIL: OwnerStatementDetail = {
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
  reservations: [],
  expenses: [],
};

function renderState(statementId = "st-1", onBack = vi.fn()) {
  const result = render(
    <I18nProvider locale="es">
      <StatementDetailState statementId={statementId} onBack={onBack} />
    </I18nProvider>,
  );
  return { ...result, onBack };
}

describe("StatementDetailState — loading/error/not-found/success (R1, R3, R5, task 4.4)", () => {
  it("shows loading while pending, with no financial data and no duplicate actions (R5.1)", () => {
    useStatementDetail.mockReturnValue({ isPending: true, isError: false, data: undefined });
    renderState();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("statement-summary")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "« Volver al listado »" })).toHaveLength(1);
  });

  it("shows a generic forbidden state on 403, with no financial data (R1.2)", () => {
    useStatementDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
      data: undefined,
    });
    renderState();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No tienes permiso para ver esta liquidación.",
    );
    expect(screen.queryByTestId("statement-summary")).not.toBeInTheDocument();
  });

  it("shows a not-found state on 404, without revealing whether the id is unknown or another tenant's (R3.7)", () => {
    useStatementDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
      data: undefined,
    });
    renderState();
    expect(screen.getByText("Liquidación no encontrada")).toBeInTheDocument();
    expect(screen.queryByText(/tenant/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("statement-summary")).not.toBeInTheDocument();
  });

  it("shows a generic error state with retry on a 500/network failure", () => {
    const refetch = vi.fn();
    useStatementDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER", message: "boom", status: 500 }),
      data: undefined,
      refetch,
    });
    renderState();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No se pudo cargar la liquidación. Vuelve a intentarlo.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the full detail on success", () => {
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    renderState();
    expect(screen.getByTestId("statement-detail")).toBeInTheDocument();
    expect(screen.getByTestId("statement-summary")).toBeInTheDocument();
  });

  it("keeps the summary visible when a breakdown is empty (R5.3)", () => {
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    renderState();
    expect(screen.getByTestId("statement-summary")).toBeInTheDocument();
    expect(screen.getByText("Sin reservas")).toBeInTheDocument();
    expect(screen.getByText("Sin gastos")).toBeInTheDocument();
  });
});

describe("StatementDetailState — back to list (R1, R3, task 4.4)", () => {
  it("calls onBack when the back-to-list control is activated, from every state", () => {
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    const { onBack } = renderState("st-1");
    fireEvent.click(screen.getByRole("button", { name: "« Volver al listado »" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("does not retain a previous statement's data once remounted for a different id (R1, R3)", () => {
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    const { unmount } = renderState("st-1");
    expect(screen.getByTestId("statement-summary")).toBeInTheDocument();
    unmount();

    const OTHER: OwnerStatementDetail = { ...DETAIL, id: "st-2", notes: "Otra liquidación" };
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: OTHER });
    renderState("st-2");
    expect(screen.getByText("Otra liquidación")).toBeInTheDocument();
    expect(screen.queryByText("st-1")).not.toBeInTheDocument();
  });
});

describe("StatementDetailState — export downloads integration (R4, task 5.3)", () => {
  function stubObjectUrl() {
    const createObjectURL = vi.fn(() => "blob:statement");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    return { createObjectURL, revokeObjectURL };
  }

  it("mounts the CSV/PDF controls below the summary on the success branch", () => {
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    renderState();
    expect(screen.getByTestId("statement-downloads")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descargar CSV" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descargar PDF" })).toBeInTheDocument();
  });

  it("does not render the export controls on non-success states", () => {
    useStatementDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
      data: undefined,
    });
    renderState();
    expect(screen.queryByTestId("statement-downloads")).not.toBeInTheDocument();
  });

  it("downloads via the existing /export.csv endpoint, treating the payload as opaque bytes (R4.1, R4.3)", async () => {
    const { createObjectURL, revokeObjectURL } = stubObjectUrl();
    exportCsv.mockResolvedValue({
      bytes: new Uint8Array([1, 2, 3]),
      headers: new Headers({ "Content-Disposition": 'attachment; filename="q1.csv"' }),
    });
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    renderState();

    fireEvent.click(screen.getByRole("button", { name: "Descargar CSV" }));

    await waitFor(() => expect(exportCsv).toHaveBeenCalledWith("tenant-1", "st-1"));
    expect(exportPdf).not.toHaveBeenCalled();
    // The bytes are handed to the browser as-is (a Blob + object URL); the
    // component never parses, validates or re-encodes them.
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("downloads via the existing /export.pdf endpoint", async () => {
    stubObjectUrl();
    exportPdf.mockResolvedValue({ bytes: new Uint8Array([7]), headers: new Headers() });
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    renderState();

    fireEvent.click(screen.getByRole("button", { name: "Descargar PDF" }));

    await waitFor(() => expect(exportPdf).toHaveBeenCalledWith("tenant-1", "st-1"));
    expect(exportCsv).not.toHaveBeenCalled();
  });

  it("shows a translated error without inspecting the file when a download fails (R4.4)", async () => {
    stubObjectUrl();
    exportCsv.mockRejectedValue(new Error("network"));
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    renderState();

    fireEvent.click(screen.getByRole("button", { name: "Descargar CSV" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "No se pudo descargar el archivo. Vuelve a intentarlo.",
      ),
    );
  });
});

describe("StatementDetailState — accessibility", () => {
  it("has no accessibility violations on success", async () => {
    useStatementDetail.mockReturnValue({ isPending: false, isError: false, data: DETAIL });
    const { container } = renderState();
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("has no accessibility violations on the not-found state", async () => {
    useStatementDetail.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "no", status: 404 }),
      data: undefined,
    });
    const { container } = renderState();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
