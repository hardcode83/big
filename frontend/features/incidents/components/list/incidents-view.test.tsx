import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, within } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esIncidents from "@/locales/es/incidents.json";
import esStates from "@/locales/es/states.json";
import { ApiError } from "@/lib/api";

const useIncidentsMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-incidents", () => ({
  useIncidents: useIncidentsMock,
}));

import { IncidentsView } from "./incidents-view";

function renderView() {
  return render(
    <I18nProvider locale="es">
      <IncidentsView />
    </I18nProvider>,
  );
}

const SAMPLE = {
  items: [
    {
      id: "i1",
      status: "CLASSIFIED",
      severity: "LOW",
      category: "WIFI",
      source: "GUEST",
      title: "WiFi va lento",
      createdAt: "2026-08-12T08:00:00Z",
    },
    {
      id: "i2",
      status: "ASSIGNED",
      severity: "HIGH",
      category: "ACCESS",
      source: "GUEST",
      title: "Problema con código de acceso",
      createdAt: "2026-08-13T08:00:00Z",
    },
  ],
  total: 2,
  page: 1,
  perPage: 20,
} as const;

describe("IncidentsView", () => {
  it("renders the loading state without a table (R2.4, R5.6)", () => {
    useIncidentsMock.mockReturnValue({
      isPending: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByText(esStates.loading.label)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders six columns and a row per item when data is present", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    const table = screen.getByRole("table");
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      esIncidents.fields.severity,
      esIncidents.fields.status,
      esIncidents.fields.title,
      esIncidents.fields.category,
      esIncidents.fields.source,
      esIncidents.fields.createdAt,
    ]);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(1 + SAMPLE.items.length);
    expect(
      within(rows[1]).getByText(esIncidents.severity.LOW),
    ).toBeInTheDocument();
    expect(
      within(rows[1]).getByText(esIncidents.status.CLASSIFIED),
    ).toBeInTheDocument();
  });

  it("does NOT render a property column in the table", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    const table = screen.getByRole("table");
    expect(table.textContent).not.toContain(esIncidents.fields.property);
  });

  it("renders the empty state when items is empty", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: [], total: 0, page: 1, perPage: 20 },
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByText(esStates["empty"].title)).toBeInTheDocument();
  });

  it("renders the generic error state with a Retry button on 5xx", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({
        status: 500,
        code: "internal",
        message: "x",
      }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByText(esStates["error"].title)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: esStates["error"].retry }),
    ).toBeInTheDocument();
  });

  it("renders the forbidden state on 403", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 403, code: "forbidden", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderView();
    expect(screen.getByText(esIncidents.fields.forbidden)).toBeInTheDocument();
  });

  it("renders validation text on 422 without echoing backend payload", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({
        status: 422,
        code: "validation_error",
        message: "cualquier cosa",
        details: { status: "invalid" },
      }),
      data: undefined,
      refetch: vi.fn(),
    });
    const { container } = renderView();
    expect(screen.getByText(esIncidents.fields.validation)).toBeInTheDocument();
    expect(container.textContent).not.toContain("cualquier cosa");
    expect(container.textContent).not.toContain("validation_error");
    expect(container.textContent).not.toContain("status"); // from details
  });

  it("treats 404 on the list as a generic error (NOT notFound)", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 404, code: "not_found", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    const { container } = renderView();
    expect(container.textContent).not.toContain(esIncidents.fields.notFound);
    expect(screen.getByText(esStates["error"].title)).toBeInTheDocument();
  });

  it("disables next button when page === lastPage (R2.5)", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: SAMPLE.items, total: 5, page: 1, perPage: 20 },
      refetch: vi.fn(),
    });
    renderView();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.nextPage }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.prevPage }),
    ).toBeDisabled();
  });

  it("disables only next button when total: 100, page: 5, perPage: 20 (lastPage = 5)", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: SAMPLE.items, total: 100, page: 5, perPage: 20 },
      refetch: vi.fn(),
    });
    renderView();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.nextPage }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.prevPage }),
    ).not.toBeDisabled();
  });

  it("computes lastPage = 1 when total = 0", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: [], total: 0, page: 1, perPage: 20 },
      refetch: vi.fn(),
    });
    renderView();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.prevPage }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.nextPage }),
    ).toBeDisabled();
  });

  it("does NOT render the description field in the table (D5, D7 — description lives only in the detail)", () => {
    useIncidentsMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch: vi.fn(),
    });
    renderView();
    const table = screen.getByRole("table");
    expect(table.textContent).not.toContain(esIncidents.fields.description);
  });

  it("passes the new filters to the hook", () => {
    let capturedFilters: unknown = null;
    useIncidentsMock.mockImplementation((filters: unknown) => {
      capturedFilters = filters;
      return {
        isPending: false,
        isError: false,
        isSuccess: true,
        data: SAMPLE,
        refetch: vi.fn(),
      };
    });
    renderView();
    fireEvent.change(
      screen.getByRole("combobox", { name: esIncidents.fields.status }),
      { target: { value: "OPEN" } },
    );
    expect(capturedFilters).toEqual({ status: "OPEN", page: 1 });
  });
});