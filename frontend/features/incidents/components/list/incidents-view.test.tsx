import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import esCommon from "@/locales/es/common.json";
import esIncidents from "@/locales/es/incidents.json";
import esNavigation from "@/locales/es/navigation.json";
import esStates from "@/locales/es/states.json";
import i18n from "@/lib/i18n";

import * as hooks from "../../hooks/use-incidents";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const mockUseIncidents = vi.spyOn(hooks, "useIncidents");

async function setupI18n() {
  await i18n.init({
    lng: "es",
    fallbackLng: "es",
    defaultNS: "common",
    ns: ["common", "navigation", "states", "incidents"],
    resources: {
      es: {
        common: esCommon,
        navigation: esNavigation,
        states: esStates,
        incidents: esIncidents,
      },
    },
    interpolation: { escapeValue: false },
  });
}

function freshWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </I18nextProvider>
    );
  };
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
  it("renders the loading state without a table (R2.4, R5.6)", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(screen.getByText(esStates.loading.label)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders six columns and a row per item when data is present", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
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

  it("does NOT render a property column in the table", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    const table = screen.getByRole("table");
    expect(table.textContent).not.toContain(esIncidents.fields.property);
  });

  it("renders the empty state when items is empty", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: [], total: 0, page: 1, perPage: 20 },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(screen.getByText(esStates["empty"].title)).toBeInTheDocument();
  });

  it("renders the generic error state with a Retry button on 5xx", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({
        status: 500,
        code: "internal",
        message: "x",
      }),
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(screen.getByText(esStates["error"].title)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: esStates["error"].retry }),
    ).toBeInTheDocument();
  });

  it("renders the forbidden state on 403", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 403, code: "forbidden", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(screen.getByText(esIncidents.fields.forbidden)).toBeInTheDocument();
  });

  it("renders validation text on 422 without echoing backend payload", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
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
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    const { container } = render(<IncidentsView />, {
      wrapper: freshWrapper(),
    });
    expect(screen.getByText(esIncidents.fields.validation)).toBeInTheDocument();
    expect(container.textContent).not.toContain("cualquier cosa");
    expect(container.textContent).not.toContain("validation_error");
    expect(container.textContent).not.toContain("status"); // from details
  });

  it("treats 404 on the list as a generic error (NOT notFound)", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 404, code: "not_found", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    const { container } = render(<IncidentsView />, {
      wrapper: freshWrapper(),
    });
    expect(container.textContent).not.toContain(esIncidents.fields.notFound);
    expect(screen.getByText(esStates["error"].title)).toBeInTheDocument();
  });

  it("disables next button when page === lastPage (R2.5)", async () => {
    await setupI18n();
    // total: 5, perPage: 20 → lastPage = 1 → next disabled
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: SAMPLE.items, total: 5, page: 1, perPage: 20 },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(
      screen.getByRole("button", { name: esIncidents.fields.nextPage }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.prevPage }),
    ).toBeDisabled();
  });

  it("disables only next button when total: 100, page: 5, perPage: 20 (lastPage = 5)", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: SAMPLE.items, total: 100, page: 5, perPage: 20 },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(
      screen.getByRole("button", { name: esIncidents.fields.nextPage }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.prevPage }),
    ).not.toBeDisabled();
  });

  it("computes lastPage = 1 when total = 0", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { items: [], total: 0, page: 1, perPage: 20 },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    expect(
      screen.getByRole("button", { name: esIncidents.fields.prevPage }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.nextPage }),
    ).toBeDisabled();
  });

  it("does NOT render the description field in the table (D5, D7 — description lives only in the detail)", async () => {
    await setupI18n();
    mockUseIncidents.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncidents>);
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    const table = screen.getByRole("table");
    expect(table.textContent).not.toContain(esIncidents.fields.description);
  });

  it("passes the new filters to the hook", async () => {
    await setupI18n();
    const refetch = vi.fn();
    const ref = {
      isPending: false,
      isError: false,
      isSuccess: true,
      data: SAMPLE,
      refetch,
    };
    let capturedFilters: unknown = null;
    mockUseIncidents.mockImplementation((filters: unknown) => {
      capturedFilters = filters;
      return ref as unknown as ReturnType<typeof hooks.useIncidents>;
    });
    const { IncidentsView } = await import("./incidents-view");
    render(<IncidentsView />, { wrapper: freshWrapper() });
    await userEvent.setup().selectOptions(
      screen.getByLabelText(esIncidents.fields.status),
      "OPEN",
    );
    expect(capturedFilters).toEqual({ status: "OPEN", page: 1 });
  });
});