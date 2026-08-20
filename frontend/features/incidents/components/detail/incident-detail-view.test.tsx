import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import { render, screen } from "@testing-library/react";
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

const mockUseIncident = vi.spyOn(hooks, "useIncident");

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

const DETAIL = {
  id: "i1",
  propertyId: "p1",
  reservationId: "r1",
  source: "GUEST",
  category: "WIFI",
  severity: "LOW",
  status: "CLASSIFIED",
  title: "WiFi va lento",
  description: "El huésped reporta que el WiFi va muy lento",
  aiSummary: null,
  assignedTechnicianId: null,
  ownerApprovalRequired: false,
  estimatedCost: null,
  approvedCost: null,
  finalCost: null,
  resolvedAt: null,
  createdAt: "2026-08-12T08:00:00Z",
  updatedAt: "2026-08-12T08:00:00Z",
} as const;

describe("IncidentDetailView", () => {
  it("renders the loading state", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(screen.getByText(esStates.loading.label)).toBeInTheDocument();
  });

  it("renders all sections when data is present", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(screen.getByText(DETAIL.id)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.propertyId)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.reservationId!)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.title)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.description)).toBeInTheDocument();
  });

  it("does NOT render the assigned-technician block when assignedTechnicianId is null (R3.6)", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(
      screen.queryByText(esIncidents.fields.assignedTechnician),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(esIncidents.fields.assignedTechnicianNote),
    ).not.toBeInTheDocument();
  });

  it("renders the assigned-technician block under a secondary section with the localized note when assignedTechnicianId is set (R3.6)", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, assignedTechnicianId: "uuid-123" },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    const { container } = render(<IncidentDetailView incidentId="i1" />, {
      wrapper: freshWrapper(),
    });
    expect(
      screen.getByText(esIncidents.fields.assignedTechnicianNote),
    ).toBeInTheDocument();
    expect(screen.getByText("uuid-123")).toBeInTheDocument();
    // No copy-UUID button / tooltip affordance:
    expect(container.querySelector("button[aria-label*='opiar']")).toBeNull();
  });

  it("renders description as plain text (D7): no <script> from string payload", async () => {
    await setupI18n();
    const dangerous = "<script>alert(1)</script>\nLínea 2";
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, description: dangerous },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText(dangerous)).toBeInTheDocument();
  });

  it("does NOT render the description block when description is null", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, description: null as unknown as string },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    const { container } = render(<IncidentDetailView incidentId="i1" />, {
      wrapper: freshWrapper(),
    });
    // description: null is falsy → no <section> for description
    expect(
      Array.from(container.querySelectorAll("h2")).find(
        (h) => h.textContent === esIncidents.fields.description,
      ),
    ).toBeUndefined();
  });

  it("renders ownerApprovalRequired note WITHOUT approve/reject buttons (R3.5)", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, ownerApprovalRequired: true },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    const { container } = render(<IncidentDetailView incidentId="i1" />, {
      wrapper: freshWrapper(),
    });
    expect(
      screen.getByText(esIncidents.fields.ownerApprovalRequired),
    ).toBeInTheDocument();
    const buttons = Array.from(container.querySelectorAll("button"));
    expect(
      buttons.some((b) =>
        /aprobar|rechazar|approve|reject/i.test(b.textContent ?? ""),
      ),
    ).toBe(false);
  });

  it("renders 404 → notFound with a back link", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 404, code: "not_found", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(screen.getByText(esIncidents.fields.notFound)).toBeInTheDocument();
    expect(
      screen.getByText(esIncidents.fields.backToList),
    ).toBeInTheDocument();
  });

  it("renders 403 → forbidden", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 403, code: "forbidden", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(screen.getByText(esIncidents.fields.forbidden)).toBeInTheDocument();
  });

  it("renders 422 → validation without echoing backend payload", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
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
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    const { container } = render(<IncidentDetailView incidentId="i1" />, {
      wrapper: freshWrapper(),
    });
    expect(screen.getByText(esIncidents.fields.validation)).toBeInTheDocument();
    expect(container.textContent).not.toContain("cualquier cosa");
    expect(container.textContent).not.toContain("validation_error");
  });

  it("renders 500 → generic error", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 500, code: "internal", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    render(<IncidentDetailView incidentId="i1" />, { wrapper: freshWrapper() });
    expect(screen.getByText(esStates.error.title)).toBeInTheDocument();
  });

  it("renders the three costs as two-decimal numbers without currency symbol (R5.5)", async () => {
    await setupI18n();
    mockUseIncident.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: {
        ...DETAIL,
        estimatedCost: "120.50",
        approvedCost: "120.00",
        finalCost: null,
      },
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useIncident>);
    const { IncidentDetailView } = await import("./incident-detail-view");
    const { container } = render(<IncidentDetailView incidentId="i1" />, {
      wrapper: freshWrapper(),
    });
    // No currency symbol anywhere
    expect(container.textContent).not.toMatch(/€|\$|EUR|USD|GBP/);
    // "—" for null final_cost
    expect(container.textContent).toContain("—");
  });
});