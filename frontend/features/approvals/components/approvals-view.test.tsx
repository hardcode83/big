import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, within } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";
import esApprovals from "@/locales/es/approvals.json";
import esStates from "@/locales/es/states.json";

const useApprovalsMock = vi.hoisted(() => vi.fn());
const useApprovalsHistoryMock = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-approvals", () => ({
  useApprovals: useApprovalsMock,
  useApprovalsHistory: useApprovalsHistoryMock,
}));

const useRespondOwnerApprovalMock = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-respond-approval", () => ({
  useRespondOwnerApproval: useRespondOwnerApprovalMock,
}));

const useHasPermissionMock = vi.hoisted(() => vi.fn(() => false));
vi.mock("@/lib/auth", () => ({
  useHasPermission: useHasPermissionMock,
}));

import { ApprovalsView } from "./approvals-view";

function renderView() {
  return render(
    <I18nProvider locale="es">
      <ApprovalsView />
    </I18nProvider>,
  );
}

const HOURS_AGO_3 = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
const MINUTES_AGO_10 = new Date(Date.now() - 10 * 60 * 1000).toISOString();

const MIXED_QUEUE = {
  items: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      relatedType: "INCIDENT" as const,
      status: "PENDING" as const,
      amount: "120.00",
      currency: "EUR",
      requestedAt: HOURS_AGO_3,
      respondedAt: null,
      incident: {
        id: "22222222-2222-2222-2222-222222222222",
        title: "Fuga en la cocina",
        category: "PLUMBING" as const,
        severity: "HIGH" as const,
      },
      property: {
        id: "33333333-3333-3333-3333-333333333333",
        name: "Pajaritos 8",
        internalCode: "PAJARITOS8",
      },
    },
    {
      id: "44444444-4444-4444-4444-444444444444",
      relatedType: "MAINTENANCE_COST" as const,
      status: "PENDING" as const,
      amount: "75.50",
      currency: "EUR",
      requestedAt: HOURS_AGO_3,
      respondedAt: null,
      incident: {
        id: "55555555-5555-5555-5555-555555555555",
        title: "Sustitución de caldera",
        category: "HVAC" as const,
        severity: "MEDIUM" as const,
      },
      property: {
        id: "66666666-6666-6666-6666-666666666666",
        name: "Centro 3",
        internalCode: "CENTRO3",
      },
    },
    {
      id: "77777777-7777-7777-7777-777777777777",
      relatedType: "OTHER" as const,
      status: "PENDING" as const,
      amount: "30.00",
      currency: "EUR",
      requestedAt: MINUTES_AGO_10,
      respondedAt: null,
      incident: null,
      property: {
        id: "88888888-8888-8888-8888-888888888888",
        name: "Playa 1",
        internalCode: "PLAYA1",
      },
    },
  ],
  total: 3,
  page: 1,
  perPage: 20,
};

const EMPTY_QUEUE = { items: [], total: 0, page: 1, perPage: 20 };

const EMPTY_HISTORY = {
  items: [],
  isPending: false,
  isError: false,
  error: null,
};

function baseMutation(overrides: Record<string, unknown> = {}) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    variables: undefined,
    ...overrides,
  };
}

describe("ApprovalsView", () => {
  it("renders the loading state without a table (R2.4)", () => {
    useApprovalsMock.mockReturnValue({ isPending: true, isError: false, data: undefined, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    expect(screen.getByText(esStates.loading.label)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders an explicit empty state, not a blank table (R2.2)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: EMPTY_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    expect(screen.getByText(esStates.empty.title)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders the generic error state with a retry button", () => {
    const refetch = vi.fn();
    useApprovalsMock.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ status: 500, code: "internal", message: "x" }),
      data: undefined,
      refetch,
    });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    expect(screen.getByText(esStates.error.title)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: esStates.error.retry }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders a mixed queue (INCIDENT/MAINTENANCE_COST/OTHER) with no raw UUID visible", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(false);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    const { container } = renderView();

    expect(screen.getByText("Pajaritos 8 (PAJARITOS8)")).toBeInTheDocument();
    expect(screen.getByText("Fuga en la cocina")).toBeInTheDocument();
    expect(screen.getByText("Sustitución de caldera")).toBeInTheDocument();
    expect(screen.getByText(esApprovals.queue.otherNote)).toBeInTheDocument();

    for (const row of MIXED_QUEUE.items) {
      expect(container.textContent).not.toContain(row.id);
      expect(container.textContent).not.toContain(row.property.id);
      if (row.incident) {
        expect(container.textContent).not.toContain(row.incident.id);
      }
    }
  });

  it("shows no approve/reject buttons for a manager (R3.2)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(false);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    expect(screen.queryByRole("button", { name: esApprovals.queue.approve })).toBeNull();
    expect(screen.queryByRole("button", { name: esApprovals.queue.reject })).toBeNull();
  });

  it("never offers decision controls on an OTHER row, even for the owner (D11)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(true);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    // Row 3 (index 3) is the OTHER row (header + 3 items).
    const otherRow = rows[3];
    expect(within(otherRow).queryByRole("button", { name: esApprovals.queue.approve })).toBeNull();
    expect(within(otherRow).getByText(esApprovals.queue.otherNote)).toBeInTheDocument();
  });

  it("shows the reject warning next to the button, always visible (R3.5)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(true);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    const warnings = screen.getAllByText(esApprovals.queue.rejectWarning);
    // One per decidable row (2 of the 3 rows offer a decision — OTHER does not).
    expect(warnings).toHaveLength(2);
  });

  it("the owner approves a row, sending response_notes verbatim (R3.1, R3.3, R3.6)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(true);
    const mutate = vi.fn();
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation({ mutate }));
    renderView();

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    const firstRow = rows[1];
    fireEvent.change(within(firstRow).getByLabelText(esApprovals.queue.notesLabel), {
      target: { value: "  Reparado por el técnico habitual  " },
    });
    fireEvent.click(within(firstRow).getByRole("button", { name: esApprovals.queue.approve }));

    expect(mutate).toHaveBeenCalledWith({
      approvalId: MIXED_QUEUE.items[0].id,
      status: "APPROVED",
      responseNotes: "  Reparado por el técnico habitual  ",
    });
  });

  it("the owner rejects a row with no notes typed (responseNotes omitted)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(true);
    const mutate = vi.fn();
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation({ mutate }));
    renderView();

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    const firstRow = rows[1];
    fireEvent.click(within(firstRow).getByRole("button", { name: esApprovals.queue.reject }));

    expect(mutate).toHaveBeenCalledWith({
      approvalId: MIXED_QUEUE.items[0].id,
      status: "REJECTED",
      responseNotes: undefined,
    });
  });

  it("shows the translated already-answered message on a 409 for that row (R3.4)", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(true);
    useRespondOwnerApprovalMock.mockReturnValue(
      baseMutation({
        isError: true,
        error: new ApiError({ status: 409, code: "already_answered", message: "x" }),
        variables: { approvalId: MIXED_QUEUE.items[0].id, status: "APPROVED" },
      }),
    );
    renderView();
    expect(screen.getByText(esApprovals.fields.alreadyAnswered)).toBeInTheDocument();
  });

  it("does not show the already-answered message on a row that was not the target of the 409", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: MIXED_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(true);
    useRespondOwnerApprovalMock.mockReturnValue(
      baseMutation({
        isError: true,
        error: new ApiError({ status: 409, code: "already_answered", message: "x" }),
        variables: { approvalId: "some-other-id", status: "APPROVED" },
      }),
    );
    renderView();
    expect(screen.queryByText(esApprovals.fields.alreadyAnswered)).toBeNull();
  });

  it("renders the short history with its result and no raw UUID", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: EMPTY_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue({
      items: [
        {
          id: "99999999-9999-9999-9999-999999999999",
          relatedType: "INCIDENT",
          status: "APPROVED",
          amount: "50.00",
          currency: "EUR",
          requestedAt: "2026-08-01T10:00:00Z",
          respondedAt: "2026-08-02T10:00:00Z",
          incident: {
            id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            title: "Cerradura atascada",
            category: "LOCK",
            severity: "LOW",
          },
          property: { id: "prop-hist", name: "Norte 2", internalCode: "NORTE2" },
        },
      ],
      isPending: false,
      isError: false,
      error: null,
    });
    useHasPermissionMock.mockReturnValue(false);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    const { container } = renderView();

    expect(screen.getByText(esApprovals.history.title)).toBeInTheDocument();
    expect(screen.getByText("Norte 2 (NORTE2)")).toBeInTheDocument();
    expect(screen.getByText(esApprovals.status.APPROVED)).toBeInTheDocument();
    expect(container.textContent).not.toContain("99999999-9999-9999-9999-999999999999");
    expect(container.textContent).not.toContain("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
  });

  it("renders an explicit empty state for the history when there is nothing answered yet", () => {
    useApprovalsMock.mockReturnValue({ isPending: false, isError: false, data: EMPTY_QUEUE, refetch: vi.fn() });
    useApprovalsHistoryMock.mockReturnValue(EMPTY_HISTORY);
    useHasPermissionMock.mockReturnValue(false);
    useRespondOwnerApprovalMock.mockReturnValue(baseMutation());
    renderView();
    expect(screen.getByText(esApprovals.history.empty)).toBeInTheDocument();
  });
});
