import type { UseMutationResult } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@/test/render";

import type { CleaningTask } from "../../data";
import type { CancelCleaningTaskInput } from "../../hooks/use-cancel-cleaning-task";
import { DetailManagerActionsBlock } from "./detail-manager-actions-block";

const task: CleaningTask = {
  id: "task-1",
  propertyId: "prop-1",
  assignedCleanerId: null,
  status: "ASSIGNED",
  scheduledStart: null,
  scheduledEnd: null,
  createdAt: "2026-08-19T18:00:00Z",
  completedAt: null,
  validationStatus: "PENDING",
  validatedAt: null,
  reservationId: null,
};

function makeCancelMutation(): UseMutationResult<
  CleaningTask,
  Error,
  CancelCleaningTaskInput
> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isError: false,
    isIdle: true,
    isPending: false,
    isSuccess: false,
    status: "idle",
    data: undefined,
    error: null,
    variables: undefined,
    context: undefined,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
  } as unknown as UseMutationResult<CleaningTask, Error, CancelCleaningTaskInput>;
}

const cleaners = [
  { id: "cleaner-1", name: "Marta", isActive: true },
];

function renderBlock(
  overrides: Partial<React.ComponentProps<typeof DetailManagerActionsBlock>> = {},
) {
  const props = {
    task,
    assignment: {
      isPending: false,
      isBlocked: false,
      onConfirm: vi.fn(),
    },
    validate: {
      isPending: false,
      isBlocked: false,
      onValidate: vi.fn(),
    },
    cancel: {
      open: false,
      onOpenChange: vi.fn(),
      mutation: makeCancelMutation(),
    },
    cleaners,
    ...overrides,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider locale="es">
        <DetailManagerActionsBlock {...props} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("DetailManagerActionsBlock (proposal R5.1/R5.2/R5.3, design D7)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("mounts AssignCleanerControl, ValidateCleaningControl and Cancel (R5.2, D7)", () => {
    renderBlock();
    expect(
      screen.getByRole("combobox", { name: "Asignar limpiadora" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Asignar" })).toBeInTheDocument();
    // ValidateCleaningControl renders nothing when status !== COMPLETED
    // (its own gating, R3.1) — both PASSED/FAILED buttons are absent
    // here. The cancel button is gated by the live-status
    // check (R4.1), so it is present for `ASSIGNED`.
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
  });

  it("hides the cancel button for terminal statuses (R4.1)", () => {
    renderBlock({ task: { ...task, status: "COMPLETED" } });
    expect(
      screen.queryByRole("button", { name: "Cancelar" }),
    ).not.toBeInTheDocument();
  });

  it("renders the validate buttons when status is COMPLETED (R3.1)", () => {
    renderBlock({
      task: { ...task, status: "COMPLETED", completedAt: "2026-08-20T11:00:00Z" },
    });
    expect(screen.getByRole("button", { name: "Validar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "No pasa" })).toBeInTheDocument();
  });

  it("disables the cancel button while a cancellation is in flight", () => {
    const mutation = makeCancelMutation();
    mutation.isPending = true;
    renderBlock({
      cancel: {
        open: false,
        onOpenChange: vi.fn(),
        mutation,
      },
    });
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeDisabled();
  });

  it("renders the manager section title", () => {
    renderBlock();
    expect(screen.getByText("Acciones del manager")).toBeInTheDocument();
  });
});