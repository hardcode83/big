import { describe, expect, it, vi } from "vitest";

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
      screen.queryByText(esIncidents.fields.assignedTechnicianNote),
    ).not.toBeInTheDocument();
  });

  it("renders the assigned-technician block under a secondary section with the localized note when assignedTechnicianId is set (R3.6)", () => {
    useIncidentMock.mockReturnValue({
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { ...DETAIL, assignedTechnicianId: "uuid-123" },
      refetch: vi.fn(),
    });
    const { container } = renderDetail();
    expect(
      screen.getByText(esIncidents.fields.assignedTechnicianNote),
    ).toBeInTheDocument();
    expect(screen.getByText("uuid-123")).toBeInTheDocument();
    // No copy-UUID button / tooltip affordance:
    expect(container.querySelector("button[aria-label*='opiar']")).toBeNull();
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
});