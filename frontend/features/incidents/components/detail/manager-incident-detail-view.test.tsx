import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";
import esIncidents from "@/locales/es/incidents.json";
import esStates from "@/locales/es/states.json";
import type { IncidentMessage, PaginatedResponse } from "@/features/incidents";
import * as incidentsData from "@/features/incidents/data";

const useIncidentMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-incidents", () => ({
  useIncident: useIncidentMock,
}));

const useHasPermissionMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { tenant_id: "tenant-1", role: "PROPERTY_MANAGER" },
  }),
  useHasPermission: useHasPermissionMock,
}));

interface TechnicianSummaryFixture {
  id: string;
  name: string;
  isActive: boolean;
}
const useTechnicianDirectoryMock = vi.hoisted(() =>
  vi.fn((): { data: TechnicianSummaryFixture[] | undefined } => ({
    data: undefined,
  })),
);
vi.mock("../../hooks/use-incident-management", () => ({
  useTechnicianDirectory: useTechnicianDirectoryMock,
}));

const getIncidentMessages = vi.fn();
const sendIncidentMessage = vi.fn();

vi.spyOn(incidentsData, "getIncidentsDataSource").mockImplementation(
  () =>
    ({
      getIncidentMessages,
      sendIncidentMessage,
    }) as unknown as ReturnType<typeof incidentsData.getIncidentsDataSource>,
);

// The actions sheet internals are exercised in `manager-incident-actions.test.tsx`;
// here we only care whether it mounts under the wrapper's permission gate.
vi.mock("./manager-incident-actions", () => ({
  ManagerIncidentActions: () => (
    <div data-testid="manager-incident-actions" />
  ),
}));

import { ManagerIncidentDetailView } from "./manager-incident-detail-view";

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

function emptyPage(
  rows: IncidentMessage[] = [],
  overrides: Partial<PaginatedResponse<IncidentMessage>> = {},
): PaginatedResponse<IncidentMessage> {
  return {
    data: rows,
    total: rows.length,
    page: 1,
    perPage: 20,
    totalPages: rows.length === 0 ? 0 : 1,
    ...overrides,
  };
}

function renderDetail() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <I18nProvider locale="es">{children}</I18nProvider>
    </QueryClientProvider>
  );
  return render(<ManagerIncidentDetailView incidentId="i1" />, { wrapper });
}

beforeEach(() => {
  useHasPermissionMock.mockReturnValue(true);
  useTechnicianDirectoryMock.mockReturnValue({ data: undefined });
  getIncidentMessages.mockReset().mockResolvedValue(emptyPage());
  sendIncidentMessage.mockReset();
});

describe("ManagerIncidentDetailView — state machine (R1, R1.5)", () => {
  it("renders the loading state via LoadingState", () => {
    useIncidentMock.mockReturnValue({
      isPending: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esStates.loading.label)).toBeInTheDocument();
  });

  it("renders 404 → EmptyState with a back link to /incidents (R1.5)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 404, code: "NOT_FOUND", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esIncidents.fields.notFound)).toBeInTheDocument();
    expect(
      screen.getByText(esIncidents.fields.backToList),
    ).toHaveAttribute("href", "/incidents");
  });

  it("renders 403 → forbidden text", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 403, code: "FORBIDDEN", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esIncidents.fields.forbidden)).toBeInTheDocument();
  });

  it("renders 422 → validation text without echoing backend payload", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "english detail",
      }),
      data: undefined,
      refetch: vi.fn(),
    });
    const { container } = renderDetail();
    expect(screen.getByText(esIncidents.fields.validation)).toBeInTheDocument();
    expect(container.textContent).not.toContain("english detail");
  });

  it("renders 500 → ErrorState with a Reintentar button that calls refetch (R1.1)", () => {
    const refetch = vi.fn();
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 500, code: "INTERNAL", message: "x" }),
      data: undefined,
      refetch,
    });
    renderDetail();
    expect(screen.getByText(esStates.error.title)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: esStates.error.retry }));
    expect(refetch).toHaveBeenCalled();
  });

  it("composes the six detail blocks plus ManagerIncidentActions in success (R1.1, R3.3)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(DETAIL.title)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.id)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.propertyId)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.description)).toBeInTheDocument();
    expect(screen.getByTestId("manager-incident-actions")).toBeInTheDocument();
  });

  it("does NOT mount ManagerIncidentActions without MANAGE_INCIDENTS (R3.3)", () => {
    useHasPermissionMock.mockReturnValue(false);
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(
      screen.queryByTestId("manager-incident-actions"),
    ).not.toBeInTheDocument();
  });

  it("resolves the technician name from the directory for the assigned id (R2.6)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, assignedTechnicianId: "uuid-123" },
      refetch: vi.fn(),
    });
    useTechnicianDirectoryMock.mockReturnValue({
      data: [{ id: "uuid-123", name: "Ana Pérez", isActive: true }],
    });
    renderDetail();
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
  });
});

describe("ManagerIncidentDetailView — tabs wiring (R1.1, R1.2)", () => {
  const contentTab = () =>
    screen.getByRole("tab", { name: esIncidents.tabs.content });
  const messagesTab = () =>
    screen.getByRole("tab", { name: esIncidents.messages.tab });

  function setDetailLoaded() {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    });
  }

  it("opens on the operational content tab, and asks for no thread until the tab is touched (R1.1, D3)", () => {
    setDetailLoaded();
    renderDetail();
    expect(contentTab()).toHaveAttribute("aria-selected", "true");
    expect(messagesTab()).toHaveAttribute("aria-selected", "false");
    expect(getIncidentMessages).not.toHaveBeenCalled();
  });

  it("requests the first page and shows the thread once the tab is opened (R1.2)", async () => {
    setDetailLoaded();
    renderDetail();
    fireEvent.click(messagesTab());
    await waitFor(() =>
      expect(getIncidentMessages).toHaveBeenCalledWith("tenant-1", "i1", 1),
    );
    expect(
      await screen.findByText(esIncidents.messages.empty.title),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(esIncidents.messages.composer.label),
    ).toBeInTheDocument();
  });

  it("hides the operational panel instead of unmounting it (R1.1)", () => {
    setDetailLoaded();
    renderDetail();
    fireEvent.click(messagesTab());
    const contentPanel = document.getElementById(
      "manager-incident-panel-content",
    );
    expect(contentPanel).toHaveAttribute("hidden");
  });

  /**
   * R1.5 with the real wrapper rather than the panel in isolation: the
   * messages read 404s, the wrapper's `messagesNotFound` flips, the whole
   * detail screen — tabs included — is replaced by the same not-found
   * EmptyState the incident read already produces.
   */
  it("replaces the whole screen with the not-found EmptyState when the messages read 404s (R1.5)", async () => {
    setDetailLoaded();
    getIncidentMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderDetail();

    fireEvent.click(messagesTab());

    await waitFor(() => {
      expect(screen.queryByRole("tablist")).toBeNull();
    });
    expect(screen.getByText(esIncidents.fields.notFound)).toBeInTheDocument();
    expect(screen.getByText(esIncidents.fields.backToList)).toHaveAttribute(
      "href",
      "/incidents",
    );
  });
});
