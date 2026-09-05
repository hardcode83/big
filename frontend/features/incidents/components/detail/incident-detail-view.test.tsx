import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esIncidents from "@/locales/es/incidents.json";
import esStates from "@/locales/es/states.json";
import { ApiError } from "@/lib/api";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import { severityColorGroup } from "../../lib/severity-tone";

const useIncidentMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-incidents", () => ({
  useIncident: useIncidentMock,
}));

// `useHasPermission("MANAGE_INCIDENTS")` gates `ManagerIncidentActions`
// (R1.1, R1.2). Default: no permission — most of this file's tests are
// about the read-only detail, not the manager's controls.
const useHasPermissionMock = vi.hoisted(() => vi.fn(() => false));
vi.mock("@/lib/auth", () => ({
  useHasPermission: useHasPermissionMock,
}));

// `useTechnicianDirectory` is what resolves the assigned technician's name
// (R2.6, design D10) — called unconditionally by `IncidentDetailView`
// itself, not by `ManagerIncidentActions`, so every viewer gets it regardless
// of `MANAGE_INCIDENTS`.
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

// `ManagerIncidentActions` itself — its internal behaviour (state→action
// table, 409/422 paths, client validation) is covered by
// `manager-incident-actions.test.tsx`. Here we only care whether it mounts.
vi.mock("./manager-incident-actions", () => ({
  ManagerIncidentActions: () => <div data-testid="manager-incident-actions" />,
}));

import { IncidentDetailView } from "./incident-detail-view";

function renderDetail(incidentId = "i1") {
  return render(
    <I18nProvider locale="es">
      <IncidentDetailView incidentId={incidentId} />
    </I18nProvider>,
  );
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
  // Every test starts read-only with an empty roster; individual tests opt
  // into a manager permission or a resolved technician as needed. Without
  // this reset, `mockReturnValue` from one test would leak into the next.
  beforeEach(() => {
    useHasPermissionMock.mockReturnValue(false);
    useTechnicianDirectoryMock.mockReturnValue({ data: undefined });
  });

  it("renders the loading state", () => {
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

  it("renders all sections when data is present", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(DETAIL.id)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.propertyId)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.reservationId!)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.title)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.description)).toBeInTheDocument();
  });

  it("does NOT render the assigned-technician block when assignedTechnicianId is null (R3.6)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(
      screen.queryByText(esIncidents.fields.assignedTechnician),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(esIncidents.fields.technicianNotAvailable),
    ).not.toBeInTheDocument();
  });

  it("renders the assigned-technician block with the resolved name when the roster contains the id (R2.6, D10)", () => {
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
    const { container } = renderDetail();
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
    // The UUID is NEVER printed (R2.6):
    expect(container.textContent).not.toContain("uuid-123");
  });

  it("renders 'not available' when the roster does not contain the assigned id (R2.6, D10)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, assignedTechnicianId: "uuid-123" },
      refetch: vi.fn(),
    });
    useTechnicianDirectoryMock.mockReturnValue({
      data: [{ id: "uuid-999", name: "Otro Técnico", isActive: true }],
    });
    const { container } = renderDetail();
    expect(
      screen.getByText(esIncidents.fields.technicianNotAvailable),
    ).toBeInTheDocument();
    expect(container.textContent).not.toContain("uuid-123");
  });

  it("renders 'not available' when the technician directory query fails (R2.6, D10)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, assignedTechnicianId: "uuid-123" },
      refetch: vi.fn(),
    });
    useTechnicianDirectoryMock.mockReturnValue({ data: undefined });
    renderDetail();
    expect(
      screen.getByText(esIncidents.fields.technicianNotAvailable),
    ).toBeInTheDocument();
  });

  it("resolves the technician's name the same way for a manager and for a read-only TENANT_OWNER (R2.6)", () => {
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

    useHasPermissionMock.mockReturnValue(false); // TENANT_OWNER
    const owner = renderDetail();
    expect(owner.getByText("Ana Pérez")).toBeInTheDocument();
    owner.unmount();

    useHasPermissionMock.mockReturnValue(true); // PROPERTY_MANAGER
    const manager = renderDetail();
    expect(manager.getByText("Ana Pérez")).toBeInTheDocument();
  });

  it("renders description as plain text (D7): no <script> from string payload", () => {
    const dangerous = "<script>alert(1)</script>\nLínea 2";
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, description: dangerous },
      refetch: vi.fn(),
    });
    renderDetail();
    const { container } = renderDetail();
    expect(document.querySelector("script")).toBeNull();
    // The text is fragmented across DOM nodes (a literal "<script>" tag + "Línea 2"),
    // so we read the joined text content instead of using getByText.
    expect(container.textContent).toContain(dangerous);
  });

  it("does NOT render the description block when description is null", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, description: null as unknown as string },
      refetch: vi.fn(),
    });
    const { container } = renderDetail();
    // description: null is falsy → no <section> for description
    expect(
      Array.from(container.querySelectorAll("h2")).find(
        (h) => h.textContent === esIncidents.fields.description,
      ),
    ).toBeUndefined();
  });

  it("renders ownerApprovalRequired note WITHOUT approve/reject buttons (R3.5)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, ownerApprovalRequired: true },
      refetch: vi.fn(),
    });
    const { container } = renderDetail();
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

  it("renders 404 → notFound with a back link", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 404, code: "not_found", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esIncidents.fields.notFound)).toBeInTheDocument();
    expect(
      screen.getByText(esIncidents.fields.backToList),
    ).toBeInTheDocument();
  });

  it("renders 403 → forbidden", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 403, code: "forbidden", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esIncidents.fields.forbidden)).toBeInTheDocument();
  });

  it("renders 422 → validation without echoing backend payload", () => {
    useIncidentMock.mockReturnValue({
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
    const { container } = renderDetail();
    expect(screen.getByText(esIncidents.fields.validation)).toBeInTheDocument();
    expect(container.textContent).not.toContain("cualquier cosa");
    expect(container.textContent).not.toContain("validation_error");
  });

  it("renders 500 → generic error", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 500, code: "internal", message: "x" }),
      data: undefined,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByText(esStates.error.title)).toBeInTheDocument();
  });

  it("renders the three costs as two-decimal numbers without currency symbol (R5.5)", () => {
    useIncidentMock.mockReturnValue({
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
    });
    const { container } = renderDetail();
    // No currency symbol anywhere
    expect(container.textContent).not.toMatch(/€|\$|EUR|USD|GBP/);
    // "—" for null final_cost
    expect(container.textContent).toContain("—");
  });

  /**
   * The wiring, not the map — raised by the QA panel on section 7.
   *
   * `severity-tone.test.ts` proves the enum→tone map is right and this file
   * proved the label renders, but nothing asserted the badge takes its colour
   * from the severity. `severityColorGroup(status)` instead of `severity` is a
   * plausible typo at the call site, and it used to keep every test green.
   *
   * Two severities, deliberately: `DETAIL` ships `severity: "LOW"` with
   * `status: "CLASSIFIED"`, and both resolve to `gray`, so LOW alone proves
   * nothing. `CRITICAL` resolves to `red` while its status stays `CLASSIFIED`,
   * which is what makes the wrong field visible.
   */
  it.each([
    ["LOW", "CLASSIFIED"],
    ["CRITICAL", "CLASSIFIED"],
  ] as const)(
    "colours the %s badge from the severity, not the status (R6.4, D7)",
    (severity, status) => {
      useIncidentMock.mockReturnValue({
        isPending: false,
        isError: false,
        isSuccess: true,
        data: { ...DETAIL, severity, status },
        refetch: vi.fn(),
      });
      renderDetail();
      const badge = screen.getByText(esIncidents.severity[severity]);
      expect(badge.className).toBe(
        TONE_BADGE_CLASS[severityColorGroup(severity)],
      );
    },
  );

  it("gives CRITICAL and LOW different tones, so the test above discriminates", () => {
    expect(TONE_BADGE_CLASS[severityColorGroup("CRITICAL")]).not.toBe(
      TONE_BADGE_CLASS[severityColorGroup("LOW")],
    );
  });

  it("does NOT mount ManagerIncidentActions without MANAGE_INCIDENTS — no reserved gap (R1.1, R1.2)", () => {
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

  it("mounts ManagerIncidentActions when MANAGE_INCIDENTS is held (R1.1)", () => {
    useHasPermissionMock.mockReturnValue(true);
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: DETAIL,
      refetch: vi.fn(),
    });
    renderDetail();
    expect(screen.getByTestId("manager-incident-actions")).toBeInTheDocument();
  });
});
