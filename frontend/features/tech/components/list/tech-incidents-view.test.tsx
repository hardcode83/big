import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";
import esTech from "@/locales/es/tech.json";
import esIncidents from "@/locales/es/incidents.json";
import * as incidentsModule from "@/features/incidents";

const TENANT = "tenant-1";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

const listIncidents = vi.fn();
const getIncidentContext = vi.fn();

vi.spyOn(incidentsModule, "getIncidentsDataSource").mockImplementation(
  () =>
    ({ listIncidents, getIncidentContext }) as unknown as ReturnType<
      typeof incidentsModule.getIncidentsDataSource
    >,
);

import { TechIncidentsView } from "./tech-incidents-view";

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <I18nProvider locale="es">{children}</I18nProvider>
    </QueryClientProvider>
  );
  return { client, ...render(<TechIncidentsView />, { wrapper }) };
}

function row(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    status: "ASSIGNED",
    severity: "HIGH",
    category: "WIFI",
    source: "GUEST",
    title: `Avería ${id}`,
    createdAt: "2026-08-12T08:00:00Z",
    ...overrides,
  };
}

function context(name: string, code: string) {
  return {
    propertyName: name,
    propertyInternalCode: code,
    addressLine1: null,
    addressLine2: null,
    city: null,
    province: null,
    postalCode: null,
    country: "ES",
    timezone: "Europe/Madrid",
    accessNotes: null,
    assignmentNote: null,
  };
}

describe("TechIncidentsView (R1)", () => {
  beforeEach(() => {
    listIncidents.mockReset();
    getIncidentContext.mockReset();
    listIncidents.mockResolvedValue({
      items: [row("i1"), row("i2")],
      total: 2,
      page: 1,
      perPage: 20,
    });
    getIncidentContext.mockImplementation((_tenant: string, id: string) =>
      Promise.resolve(context(`Piso ${id}`, `MAD-${id}`)),
    );
  });

  it("requests the list with no parameter identifying the technician (R1.1)", async () => {
    renderView();

    await waitFor(() => expect(listIncidents).toHaveBeenCalled());
    const filters = listIncidents.mock.calls[0][1] as Record<string, unknown>;
    expect(Object.keys(filters).sort()).toEqual(["page", "perPage"]);
    expect(JSON.stringify(filters)).not.toMatch(/technician/i);
  });

  it("shows the property of each row from the context key (R1.2, R1.3)", async () => {
    renderView();

    expect(await screen.findByText("Piso i1")).toBeInTheDocument();
    expect(screen.getByText("MAD-i1")).toBeInTheDocument();
    expect(screen.getByText("Piso i2")).toBeInTheDocument();
  });

  it("stores each row's context under the very key the detail reads (R1.3)", async () => {
    const { client } = renderView();

    await waitFor(() =>
      expect(
        client.getQueryData(incidentsModule.incidentsKeys.context(TENANT, "i1")),
      ).toBeDefined(),
    );
  });

  it("degrades a failed row context to an em-dash without taking the list down (D4)", async () => {
    getIncidentContext.mockImplementation((_tenant: string, id: string) =>
      id === "i1"
        ? Promise.reject(new ApiError({ status: 500, code: "x", message: "y" }))
        : Promise.resolve(context("Piso i2", "MAD-i2")),
    );
    renderView();

    expect(await screen.findByText("Piso i2")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByText(esTech.common.empty).length).toBeGreaterThan(0),
    );
    expect(screen.getByText("Avería i1")).toBeInTheDocument();
  });

  it("renders the rows in the order the response serves, without re-sorting (R1.4)", async () => {
    listIncidents.mockResolvedValue({
      items: [
        row("newest", { createdAt: "2026-08-20T08:00:00Z" }),
        row("oldest", { createdAt: "2026-01-01T08:00:00Z" }),
      ],
      total: 2,
      page: 1,
      perPage: 20,
    });
    renderView();

    await screen.findByText("Avería newest");
    const titles = screen
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "");
    expect(titles[0]).toContain("Avería newest");
    expect(titles[1]).toContain("Avería oldest");
  });

  it("says on screen that the list includes closed incidents (R1.4)", async () => {
    renderView();
    expect(
      await screen.findByText(esTech.list.includesClosed),
    ).toBeInTheDocument();
  });

  it("filters by a single status and clears it on a second tap (R1.5)", async () => {
    renderView();
    await screen.findByText("Avería i1");

    fireEvent.click(screen.getByRole("button", { name: esIncidents.status.ACCEPTED }));

    await waitFor(() => {
      const filters = listIncidents.mock.calls.at(-1)?.[1] as Record<
        string,
        unknown
      >;
      expect(filters.status).toBe("ACCEPTED");
    });

    fireEvent.click(screen.getByRole("button", { name: esIncidents.status.ACCEPTED }));

    await waitFor(() => {
      const filters = listIncidents.mock.calls.at(-1)?.[1] as Record<
        string,
        unknown
      >;
      expect(filters).not.toHaveProperty("status");
    });
  });

  it("renders the shared EmptyState on an empty response (R1.6)", async () => {
    listIncidents.mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      perPage: 20,
    });
    renderView();

    expect(await screen.findByText(esTech.list.empty.title)).toBeInTheDocument();
  });

  it("renders an alert without the error detail when the list fails (R1.6, R6.2)", async () => {
    listIncidents.mockRejectedValue(
      new ApiError({ status: 403, code: "BOOM", message: "stack trace here" }),
    );
    renderView();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(esTech.list.error.title);
    expect(alert).not.toHaveTextContent("stack trace here");
    expect(alert).not.toHaveTextContent("BOOM");
  });

  it("does not retry a 4xx on the list (retryPolicy wiring, R1.6)", async () => {
    listIncidents.mockRejectedValue(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "x" }),
    );
    renderView();

    await screen.findByRole("alert");
    expect(listIncidents).toHaveBeenCalledTimes(1);
  });

  it("accumulates pages behind `load more` and keeps the earlier contexts (R1.4)", async () => {
    listIncidents.mockImplementation(
      (_tenant: string, filters: { page: number }) =>
        Promise.resolve({
          items: [row(`p${filters.page}`)],
          total: 2,
          page: filters.page,
          perPage: 20,
        }),
    );
    renderView();

    await screen.findByText("Avería p1");
    fireEvent.click(screen.getByRole("button", { name: esTech.list.loadMore }));

    expect(await screen.findByText("Avería p2")).toBeInTheDocument();
    expect(screen.getByText("Avería p1")).toBeInTheDocument();
    // The first page's context was fetched once and is still the same entry.
    expect(
      getIncidentContext.mock.calls.filter(([, id]) => id === "p1"),
    ).toHaveLength(1);
  });

  it("shows a loading region marked aria-busy while the list is pending", () => {
    listIncidents.mockReturnValue(new Promise(() => {}));
    renderView();

    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });
});
