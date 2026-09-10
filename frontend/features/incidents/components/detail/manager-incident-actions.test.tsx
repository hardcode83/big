import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { IncidentDetailDto, TechnicianSummary } from "../../data";
import { ManagerIncidentActions } from "./manager-incident-actions";

/**
 * `react-i18next` is mocked to the identity function (same pattern as
 * `blocked-transitions-section.test.tsx`): `t(key)` returns the bare key, so
 * assertions read `manager.conflict.closed` etc. directly and never depend on
 * the actual Spanish/English copy in `locales/*`.
 */
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const classifyState = vi.hoisted(() => ({
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  isError: false,
  error: null as unknown,
  data: undefined as { status: string } | undefined,
}));
const triageState = vi.hoisted(() => ({
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  isError: false,
  error: null as unknown,
  data: undefined as { status: string } | undefined,
}));
const assignState = vi.hoisted(() => ({
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  isError: false,
  error: null as unknown,
  data: undefined as { status: string } | undefined,
}));
const cancelState = vi.hoisted(() => ({
  mutate: vi.fn(),
  isPending: false,
  isSuccess: false,
  isError: false,
  error: null as unknown,
  data: undefined as { status: string } | undefined,
}));
const techniciansState = vi.hoisted(() => ({
  data: undefined as TechnicianSummary[] | undefined,
}));

vi.mock("../../hooks/use-incident-management", () => ({
  useClassifyIncident: () => classifyState,
  useTriageIncident: () => triageState,
  useAssignIncident: () => assignState,
  useCancelIncident: () => cancelState,
  useTechnicianDirectory: () => techniciansState,
}));

function resetMutation(state: typeof classifyState) {
  state.mutate.mockReset();
  state.isPending = false;
  state.isSuccess = false;
  state.isError = false;
  state.error = null;
  state.data = undefined;
}

beforeEach(() => {
  resetMutation(classifyState);
  resetMutation(triageState);
  resetMutation(assignState);
  resetMutation(cancelState);
  techniciansState.data = undefined;
});

const BASE: IncidentDetailDto = {
  id: "incident-1",
  propertyId: "p1",
  reservationId: null,
  source: "GUEST",
  category: "WIFI",
  severity: "LOW",
  status: "CLASSIFIED",
  title: "WiFi va lento",
  description: "El huésped reporta que el WiFi va muy lento",
  aiSummary: null,
  assignedTechnicianId: null,
  ownerApprovalRequired: false,
  etaAt: null,
  estimatedCost: null,
  approvedCost: null,
  finalCost: null,
  materials: null,
  resolvedAt: null,
  createdAt: "2026-08-12T08:00:00Z",
  updatedAt: "2026-08-12T08:00:00Z",
};

function renderActions(incident: Partial<IncidentDetailDto> = {}) {
  return render(<ManagerIncidentActions incident={{ ...BASE, ...incident }} />);
}

describe("ManagerIncidentActions — status → action table (R1.3-R1.5)", () => {
  it("OPEN offers classify, triage and cancel, but not assign", () => {
    renderActions({ status: "OPEN" });
    expect(screen.getByRole("button", { name: "manager.actions.classify" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "manager.actions.triage" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "manager.actions.cancel" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "manager.actions.assign" }),
    ).not.toBeInTheDocument();
  });

  it("CLASSIFIED offers assign, triage and cancel, but not classify", () => {
    renderActions({ status: "CLASSIFIED" });
    expect(screen.getByRole("button", { name: "manager.actions.assign" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "manager.actions.triage" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "manager.actions.cancel" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "manager.actions.classify" }),
    ).not.toBeInTheDocument();
  });

  it("labels the assign action 'reassign' once the incident already has an assignee (R2.2)", () => {
    renderActions({ status: "CLASSIFIED", assignedTechnicianId: "tech-1" });
    expect(
      screen.getByRole("button", { name: "manager.actions.reassign" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "manager.actions.assign" }),
    ).not.toBeInTheDocument();
  });

  it("AWAITING_OWNER_APPROVAL offers only cancel, plus the status note, and NEVER a respond-to-approval control (R1.4)", () => {
    renderActions({ status: "AWAITING_OWNER_APPROVAL" });
    expect(screen.getByRole("button", { name: "manager.actions.cancel" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "manager.actions.assign" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "manager.actions.triage" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "manager.actions.classify" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("manager.statusNote.awaiting-owner")).toBeInTheDocument();
  });

  it("RESOLVED offers no action at all (R1.5)", () => {
    renderActions({ status: "RESOLVED" });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("manager.none")).toBeInTheDocument();
  });

  it("CANCELLED offers no action at all (R1.5)", () => {
    renderActions({ status: "CANCELLED" });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("manager.none")).toBeInTheDocument();
  });
});

describe("ManagerIncidentActions — 403 hides the whole section (R6.2)", () => {
  it("shows the forbidden text and no buttons when any mutation carries a 403", () => {
    classifyState.error = new ApiError({
      status: 403,
      code: "forbidden",
      message: "top secret backend detail",
    });
    renderActions({ status: "OPEN" });
    expect(screen.getByText("fields.forbidden")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("top secret backend detail")).not.toBeInTheDocument();
  });
});

describe("ManagerIncidentActions — 409 conflict paths (R6.1)", () => {
  it("'closed': a stale error surfaces on a status that now offers no actions", () => {
    triageState.error = new ApiError({
      status: 409,
      code: "CONFLICT",
      message: "incident is closed, technical detail",
    });
    renderActions({ status: "CANCELLED" });
    expect(screen.getByText("manager.conflict.closed")).toBeInTheDocument();
    expect(screen.queryByText(/technical detail/)).not.toBeInTheDocument();
  });

  it("'awaiting-owner': shown inside the cancel confirmation when cancel 409s while the incident awaits the owner", () => {
    cancelState.error = new ApiError({
      status: 409,
      code: "CONFLICT",
      message: "awaiting owner, technical detail",
    });
    renderActions({ status: "AWAITING_OWNER_APPROVAL" });
    fireEvent.click(screen.getByRole("button", { name: "manager.actions.cancel" }));
    expect(screen.getByText("manager.conflict.awaiting-owner")).toBeInTheDocument();
    expect(screen.queryByText(/technical detail/)).not.toBeInTheDocument();
  });

  it("'out-of-order': shown inside the assign sheet when assign 409s on an ordinary mid-cycle status", () => {
    assignState.error = new ApiError({
      status: 409,
      code: "CONFLICT",
      message: "status changed, technical detail",
    });
    renderActions({ status: "ASSIGNED", assignedTechnicianId: "tech-1" });
    fireEvent.click(screen.getByRole("button", { name: "manager.actions.reassign" }));
    expect(screen.getByText("manager.conflict.out-of-order")).toBeInTheDocument();
    expect(screen.queryByText(/technical detail/)).not.toBeInTheDocument();
  });

  it("the triage-on-OPEN nuance: NOT the generic 'out-of-order', but 'triage-not-classified' (design D9)", () => {
    triageState.error = new ApiError({
      status: 409,
      code: "CONFLICT",
      message: "technical detail",
    });
    renderActions({ status: "OPEN" });
    fireEvent.click(screen.getByRole("button", { name: "manager.actions.triage" }));
    expect(screen.getByText("manager.conflict.triage-not-classified")).toBeInTheDocument();
    expect(screen.queryByText("manager.conflict.out-of-order")).not.toBeInTheDocument();
  });
});

describe("ManagerIncidentActions — assign (R2.1-R2.5)", () => {
  function openAssign(incident: Partial<IncidentDetailDto> = {}) {
    renderActions({ status: "CLASSIFIED", ...incident });
    const label = incident.assignedTechnicianId
      ? "manager.actions.reassign"
      : "manager.actions.assign";
    fireEvent.click(screen.getByRole("button", { name: label }));
  }

  it("only ACTIVE technicians are selectable; inactive ones are not offered (R2.1)", () => {
    techniciansState.data = [
      { id: "t-active", name: "Ana Activa", isActive: true },
      { id: "t-inactive", name: "Bruno Inactivo", isActive: false },
    ];
    openAssign();
    expect(screen.getByRole("option", { name: "Ana Activa" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Bruno Inactivo" })).not.toBeInTheDocument();
  });

  it("starts unselected, and disables confirm until a technician is chosen (R2.2)", () => {
    techniciansState.data = [{ id: "t-active", name: "Ana Activa", isActive: true }];
    openAssign({ assignedTechnicianId: "someone-else" });
    const select = screen.getByLabelText("manager.assign.technicianLabel") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(
      screen.getByRole("button", { name: "manager.assign.confirm" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(screen.getByText("manager.assign.reassignWarning")).toBeInTheDocument();
  });

  it("rejects a note over 2000 characters client-side, without calling mutate (R2.3)", () => {
    techniciansState.data = [{ id: "t-active", name: "Ana Activa", isActive: true }];
    openAssign();
    fireEvent.change(screen.getByLabelText("manager.assign.technicianLabel"), {
      target: { value: "t-active" },
    });
    fireEvent.change(screen.getByLabelText("manager.assign.noteLabel"), {
      target: { value: "a".repeat(2001) },
    });
    const submit = screen.getByRole("button", { name: "manager.assign.confirm" });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.click(submit);
    expect(assignState.mutate).not.toHaveBeenCalled();
  });

  it("rejects a note with control characters client-side, without calling mutate (R2.3)", () => {
    techniciansState.data = [{ id: "t-active", name: "Ana Activa", isActive: true }];
    openAssign();
    fireEvent.change(screen.getByLabelText("manager.assign.technicianLabel"), {
      target: { value: "t-active" },
    });
    fireEvent.change(screen.getByLabelText("manager.assign.noteLabel"), {
      target: { value: "note with \x07 bell" },
    });
    const submit = screen.getByRole("button", { name: "manager.assign.confirm" });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.click(submit);
    expect(assignState.mutate).not.toHaveBeenCalled();
  });

  it("submits with a valid technician and note", async () => {
    techniciansState.data = [{ id: "t-active", name: "Ana Activa", isActive: true }];
    openAssign();
    fireEvent.change(screen.getByLabelText("manager.assign.technicianLabel"), {
      target: { value: "t-active" },
    });
    fireEvent.change(screen.getByLabelText("manager.assign.noteLabel"), {
      target: { value: "Trae la escalera" },
    });
    fireEvent.click(screen.getByRole("button", { name: "manager.assign.confirm" }));
    await waitFor(() =>
      expect(assignState.mutate).toHaveBeenCalledWith(
        {
          incidentId: "incident-1",
          technicianId: "t-active",
          assignmentNote: "Trae la escalera",
        },
        expect.any(Object),
      ),
    );
  });

  it("shows the localized 422 invalid-technician message, never the technical error.message (R2.5)", () => {
    assignState.error = new ApiError({
      status: 422,
      code: "VALIDATION_ERROR",
      message: "InvalidTechnicianError: not an active technician of this tenant",
    });
    openAssign();
    expect(screen.getByText("manager.errors.invalid-technician")).toBeInTheDocument();
    expect(
      screen.queryByText(/InvalidTechnicianError/),
    ).not.toBeInTheDocument();
  });
});

describe("ManagerIncidentActions — triage (R3.1-R3.4)", () => {
  function openTriage(incident: Partial<IncidentDetailDto> = {}) {
    renderActions({ status: "CLASSIFIED", category: "WIFI", severity: "LOW", ...incident });
    fireEvent.click(screen.getByRole("button", { name: "manager.actions.triage" }));
  }

  it("precharges category, severity and cost with the incident's current values", () => {
    openTriage({ estimatedCost: "45.00" });
    expect((screen.getByLabelText("manager.triage.categoryLabel") as HTMLSelectElement).value).toBe(
      "WIFI",
    );
    expect((screen.getByLabelText("manager.triage.severityLabel") as HTMLSelectElement).value).toBe(
      "LOW",
    );
    expect((screen.getByLabelText("manager.triage.costLabel") as HTMLInputElement).value).toBe(
      "45.00",
    );
  });

  it("rejects a cost that is not a positive decimal, without calling mutate (R3.2)", () => {
    openTriage();
    // A negative number is a valid `<input type="number">` value (unlike
    // free text, jsdom does not coerce it to empty) but fails
    // `isPositiveDecimal` — this is what actually disables the button,
    // rather than "no changes at all" (matching `resolve-incident-dialog`'s
    // own precedent: a disabled submit blocks the click, so `mutate` not
    // being called — not an inline error appearing — is the assertion).
    fireEvent.change(screen.getByLabelText("manager.triage.costLabel"), {
      target: { value: "-5" },
    });
    const submit = screen.getByRole("button", { name: "manager.triage.confirm" });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.click(submit);
    expect(triageState.mutate).not.toHaveBeenCalled();
  });

  it("sends only the fields that changed (R3.2)", async () => {
    openTriage({ estimatedCost: "10.00" });
    fireEvent.change(screen.getByLabelText("manager.triage.severityLabel"), {
      target: { value: "HIGH" },
    });
    fireEvent.click(screen.getByRole("button", { name: "manager.triage.confirm" }));
    await waitFor(() =>
      expect(triageState.mutate).toHaveBeenCalledWith(
        { incidentId: "incident-1", severity: "HIGH" },
        expect.any(Object),
      ),
    );
  });

  it("communicates the owner-approval gate after a triage that pushes the incident over the cost threshold (R3.3)", () => {
    triageState.isSuccess = true;
    triageState.data = { status: "AWAITING_OWNER_APPROVAL" };
    renderActions({ status: "AWAITING_OWNER_APPROVAL" });
    expect(screen.getByText("manager.postTriage.awaitingApproval")).toBeInTheDocument();
  });

  it("communicates that the incident is still pending classification after a triage that leaves it OPEN (R3.4)", () => {
    triageState.isSuccess = true;
    triageState.data = { status: "OPEN" };
    renderActions({ status: "OPEN" });
    expect(screen.getByText("manager.postTriage.stillOpen")).toBeInTheDocument();
  });
});

describe("ManagerIncidentActions — classify (R4.1-R4.2)", () => {
  it("communicates the below-threshold outcome when the classifier leaves the incident OPEN (R4.2)", () => {
    classifyState.isSuccess = true;
    classifyState.data = { status: "OPEN" };
    renderActions({ status: "OPEN" });
    expect(screen.getByText("manager.postClassify.stillOpen")).toBeInTheDocument();
    // The button to run manual triage is offered in the same place:
    expect(screen.getByRole("button", { name: "manager.actions.triage" })).toBeInTheDocument();
  });

  it("calls classify with no body", () => {
    renderActions({ status: "OPEN" });
    fireEvent.click(screen.getByRole("button", { name: "manager.actions.classify" }));
    expect(classifyState.mutate).toHaveBeenCalledWith({ incidentId: "incident-1" });
  });

  it("clears a stale classify 'still open' notice once a later triage classifies the incident (R4.2, R3.4)", () => {
    // Reproduces the cross-mutation sequence a snapshot-based check would get
    // wrong: the manager relaunches the classifier (incident stays OPEN, the
    // "still needs classification" notice is correct at this point), then
    // separately triages with category+severity, which transitions the
    // incident to CLASSIFIED via `classify_by_triage` — a DIFFERENT mutation
    // that never touches `classify.isSuccess`/`classify.data`. The stale
    // classify notice must not survive alongside the now-CLASSIFIED action
    // set.
    classifyState.isSuccess = true;
    classifyState.data = { status: "OPEN" };
    const { rerender } = renderActions({ status: "OPEN" });
    expect(screen.getByText("manager.postClassify.stillOpen")).toBeInTheDocument();

    triageState.isSuccess = true;
    triageState.data = { status: "CLASSIFIED" };
    // A real re-render from the parent's refetch after `onSettled`
    // invalidates the detail query — the incident prop itself now reflects
    // the fresh CLASSIFIED status.
    rerender(<ManagerIncidentActions incident={{ ...BASE, status: "CLASSIFIED" }} />);

    expect(screen.queryByText("manager.postClassify.stillOpen")).not.toBeInTheDocument();
  });
});

describe("ManagerIncidentActions — cancel (R5.1-R5.3)", () => {
  it("asks for confirmation naming the consequence before cancelling, and sends no reason", async () => {
    renderActions({ status: "CLASSIFIED" });
    fireEvent.click(screen.getByRole("button", { name: "manager.actions.cancel" }));
    expect(screen.getByText("manager.cancel.body")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "manager.cancel.confirm" }));
    await waitFor(() =>
      expect(cancelState.mutate).toHaveBeenCalledWith(
        { incidentId: "incident-1" },
        expect.any(Object),
      ),
    );
  });
});
