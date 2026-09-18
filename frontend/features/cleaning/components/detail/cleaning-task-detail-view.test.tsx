import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "@/lib/auth";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";
import { fireEvent, render, screen, waitFor } from "@/test/render";
import esCleaning from "@/locales/es/cleaning.json";
import type { CleanerDataSource } from "@/features/cleaner/data";
import * as cleanerData from "@/features/cleaner/data";

import type {
  CleanerSummary,
  CleaningTask,
  PropertySummary,
} from "../../data";
import type { CancelCleaningTaskInput } from "../../hooks/use-cancel-cleaning-task";

const useCleaningTaskMock = vi.hoisted(() => vi.fn());
const usePropertyDirectoryMock = vi.hoisted(() =>
  vi.fn((): { data: PropertySummary[] | undefined } => ({ data: undefined })),
);
const useCleanerDirectoryMock = vi.hoisted(() =>
  vi.fn((): { data: CleanerSummary[] | undefined } => ({ data: undefined })),
);
const useAssignCleaningTaskMock = vi.hoisted(() => vi.fn());
const useValidateCleaningTaskMock = vi.hoisted(() => vi.fn());
const useCancelCleaningTaskMock = vi.hoisted(() => vi.fn());
const useHasPermissionMock = vi.hoisted(() =>
  vi.fn((_permission: Permission): boolean => true),
);

vi.mock("../../hooks/use-cleaning-task", () => ({
  useCleaningTask: useCleaningTaskMock,
}));
vi.mock("../../hooks/use-cleaning-data", () => ({
  usePropertyDirectory: usePropertyDirectoryMock,
  useCleanerDirectory: useCleanerDirectoryMock,
}));
vi.mock("../../hooks/use-assign-cleaning-task", () => ({
  useAssignCleaningTask: useAssignCleaningTaskMock,
}));
vi.mock("../../hooks/use-validate-cleaning-task", () => ({
  useValidateCleaningTask: useValidateCleaningTaskMock,
}));
vi.mock("../../hooks/use-cancel-cleaning-task", () => ({
  useCancelCleaningTask: useCancelCleaningTaskMock,
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1", role: "PROPERTY_MANAGER" } }),
  useHasPermission: useHasPermissionMock,
}));

// Section 3 (D4/D6): `ManagerCleaningTaskMessagesPanel` is now always mounted
// alongside the operational tab, so its `useCleanerTaskMessages` call always
// resolves a tenant via `useAuth` (mocked above) and always goes through the
// cleaner data source. The panel's own query is lazy (`enabled` starts
// false), so `getTaskMessages` is never actually invoked by these tests, but
// the spy still has to exist so `getCleanerDataSource()` resolves to
// something callable instead of hitting the real HTTP data source.
const getTaskMessagesMock = vi.fn().mockResolvedValue({
  data: [],
  total: 0,
  page: 1,
  perPage: 20,
  totalPages: 0,
});
const sendTaskMessageMock = vi.fn();
vi.spyOn(cleanerData, "getCleanerDataSource").mockImplementation(
  (): CleanerDataSource =>
    ({
      getTaskMessages: getTaskMessagesMock,
      sendTaskMessage: sendTaskMessageMock,
    }) as unknown as CleanerDataSource,
);

import { CleaningTaskDetailView } from "./cleaning-task-detail-view";

const PROPERTY_UUID = "8f14e45f-ceea-467a-9b7c-9d7c1a2b3c4d";
const CLEANER_UUID = "c9f0f895-fb98-4b41-a54b-2e1a7c0d9e8f";
const RESERVATION_UUID = "0d4ce0e0-1234-4abc-9b7c-9d7c1a2b3c4d";

const task: CleaningTask = {
  id: "task-1",
  propertyId: PROPERTY_UUID,
  assignedCleanerId: CLEANER_UUID,
  status: "ASSIGNED",
  scheduledStart: "2026-08-20T09:00:00Z",
  scheduledEnd: "2026-08-20T11:00:00Z",
  createdAt: "2026-08-19T18:00:00Z",
  completedAt: null,
  validationStatus: "PENDING",
  validatedAt: null,
  reservationId: RESERVATION_UUID,
};

function makeQueryResult(
  overrides: Partial<UseQueryResult<CleaningTask, Error>> = {},
): UseQueryResult<CleaningTask, Error> {
  return {
    isPending: false,
    isError: false,
    isSuccess: true,
    isFetching: false,
    isLoading: false,
    isStale: false,
    data: task,
    error: null,
    status: "success",
    refetch: vi.fn(),
    fetchStatus: "idle",
    ...overrides,
  } as UseQueryResult<CleaningTask, Error>;
}

function makeMutation(
  overrides: Partial<UseMutationResult<CleaningTask, Error, unknown>> = {},
): UseMutationResult<CleaningTask, Error, unknown> {
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
    ...overrides,
  } as unknown as UseMutationResult<CleaningTask, Error, unknown>;
}

function renderView() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider locale="es">
        <CleaningTaskDetailView taskId="task-1" />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("CleaningTaskDetailView (proposal R1-R6)", () => {
  beforeEach(() => {
    useCleaningTaskMock.mockReturnValue(makeQueryResult());
    usePropertyDirectoryMock.mockReturnValue({
      data: [
        {
          id: PROPERTY_UUID,
          name: "Redes 11",
          internalCode: "REDES11",
          currentOperationalState: "AWAITING_CLEANING",
        },
      ],
    });
    useCleanerDirectoryMock.mockReturnValue({
      data: [{ id: CLEANER_UUID, name: "Marta Ruiz", isActive: true }],
    });
    useAssignCleaningTaskMock.mockReturnValue(makeMutation());
    useValidateCleaningTaskMock.mockReturnValue(makeMutation());
    useCancelCleaningTaskMock.mockReturnValue(makeMutation());
    useHasPermissionMock.mockReturnValue(true);
  });

  it("renders the loading state when the query is pending (R1.3)", () => {
    useCleaningTaskMock.mockReturnValue(
      makeQueryResult({ isPending: true, isSuccess: false, data: undefined }),
    );
    renderView();
    expect(screen.getByText("Cargando…")).toBeInTheDocument();
  });

  it("renders the not-found state with a back link (R1.2)", () => {
    useCleaningTaskMock.mockReturnValue(
      makeQueryResult({
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new ApiError({ status: 404, code: "not_found", message: "x" }),
      }),
    );
    renderView();
    // The empty-state title plus the "back to list" link with href="/cleaning".
    expect(screen.getByText("Tarea no disponible")).toBeInTheDocument();
    const backLinks = screen.getAllByRole("link", {
      name: /Volver al listado/,
    });
    expect(backLinks.length).toBe(1);
    expect(backLinks[0]).toHaveAttribute("href", "/cleaning");
  });

  it("renders the forbidden state (R1.4)", () => {
    useCleaningTaskMock.mockReturnValue(
      makeQueryResult({
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new ApiError({ status: 403, code: "forbidden", message: "x" }),
      }),
    );
    renderView();
    expect(
      screen.getByText("No tienes permiso para ver esta limpieza."),
    ).toBeInTheDocument();
  });

  it("renders the validation state without echoing the backend payload (R1.4)", () => {
    useCleaningTaskMock.mockReturnValue(
      makeQueryResult({
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new ApiError({
          status: 422,
          code: "validation_error",
          message: "DO NOT LEAK",
          details: { foo: "bar" },
        }),
      }),
    );
    const { container } = renderView();
    expect(
      screen.getByText("Identificador de tarea inválido."),
    ).toBeInTheDocument();
    expect(container.textContent).not.toContain("DO NOT LEAK");
    expect(container.textContent).not.toContain("validation_error");
  });

  it("renders the generic error state with a retry button (R1.4)", () => {
    const refetch = vi.fn();
    useCleaningTaskMock.mockReturnValue(
      makeQueryResult({
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new Error("network broken"),
        refetch,
      }),
    );
    renderView();
    expect(
      screen.getByText("No se pudo cargar el detalle"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reintentar" }),
    ).toBeInTheDocument();
  });

  it("renders the success state with all blocks (R1.1, R2-R5)", () => {
    renderView();
    // Header (R2.1): status + validation labels (the latter is the new
    // section-4 namespace key, the former is the existing catalog).
    expect(screen.getByText("Asignada")).toBeInTheDocument();
    expect(screen.getByText("Validación")).toBeInTheDocument();
    // Identifying (R3.1): property code + name, never the id.
    expect(screen.getByText("REDES11")).toBeInTheDocument();
    expect(screen.getByText("Redes 11")).toBeInTheDocument();
    // Identifying (R3.2): reservation id rendered as the code.
    expect(screen.getByText(RESERVATION_UUID)).toBeInTheDocument();
    // Assigned cleaner (R3.3): resolved name, never the uuid.
    // The name also appears as the candidate <option> in
    // AssignCleanerControl, so the assertion is "at least one occurrence
    // is the cleaner block's text", matching the listing's own assertion
    // (`cleaning-task-row.test.tsx`).
    expect(
      screen
        .getAllByText("Marta Ruiz")
        .some((node) => node.tagName !== "OPTION"),
    ).toBe(true);
    // Manager actions (R5.1): the three controls mount behind
    // MANAGE_CLEANING_TASKS — AssignCleanerControl + Cancel button.
    expect(
      screen.getByRole("combobox", { name: "Asignar limpiadora" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
    // Context links (R4): "back to list" appears in both the header (D8) and
    // the context-links row, so two matches are expected. The other two
    // links are unique.
    expect(
      screen.getAllByRole("link", { name: /Volver al listado/ })[0],
    ).toHaveAttribute("href", "/cleaning");
    expect(
      screen.getByRole("link", { name: /Ver vivienda/ }),
    ).toHaveAttribute("href", `/properties/${PROPERTY_UUID}`);
    expect(
      screen.getByRole("link", { name: /Ver reserva/ }),
    ).toHaveAttribute("href", `/reservations/${RESERVATION_UUID}`);
  });

  it("hides the manager-actions block without MANAGE_CLEANING_TASKS (R5.1)", () => {
    useHasPermissionMock.mockImplementation((perm: string) =>
      perm === "READ_PROPERTIES" || perm === "READ_RESERVATIONS",
    );
    renderView();
    expect(
      screen.queryByRole("combobox", { name: "Asignar limpiadora" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });

  it("does not render the 'view reservation' link when reservationId is null (R4.3)", () => {
    useCleaningTaskMock.mockReturnValue(
      makeQueryResult({
        data: { ...task, reservationId: null },
      }),
    );
    renderView();
    expect(
      screen.queryByRole("link", { name: /Ver reserva/ }),
    ).not.toBeInTheDocument();
  });

  it("hides the cross-resource links without READ_PROPERTIES / READ_RESERVATIONS (R4.1, R4.3)", () => {
    useHasPermissionMock.mockImplementation((perm: string) =>
      perm === "MANAGE_CLEANING_TASKS",
    );
    renderView();
    expect(
      screen.queryByRole("link", { name: /Ver vivienda/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Ver reserva/ }),
    ).not.toBeInTheDocument();
  });

  it("declares a single live region for the three mutations (R5.5)", () => {
    renderView();
    const liveRegions = screen.getAllByRole("status");
    // The i18n provider emits one (empty here), the manager-actions
    // section may emit one of its own — the contract under test is
    // "exactly one polite live region for the mutation announcements".
    const polite = liveRegions.filter((el) =>
      el.getAttribute("aria-live") === "polite",
    );
    expect(polite.length).toBeGreaterThanOrEqual(1);
    // None of the polite regions carries `aria-busy` (that would
    // belong to the LoadingState, which is not mounted on success).
    polite.forEach((el) => {
      expect(el.getAttribute("aria-busy")).not.toBe("true");
    });
  });

  it("does not print the raw cleaner uuid in the visible text (R3.1)", () => {
    // The uuid IS in `AssignCleanerControl`'s `<option value>` (it is the
    // id the PATCH sends), so the assertion is the *text content*, not
    // the raw HTML. Same shape the listing uses for the cleaner cell.
    renderView();
    expect(document.body.textContent ?? "").not.toContain(CLEANER_UUID);
  });

  it("announces the status-specific copy in the live region, not the generic 'unknown' (R5.4)", () => {
    // A 403 on the assign mutation must paint the status-specific key
    // (cleaning:assign.error.forbidden), not the generic 'Ha ocurrido un
    // error inesperado' from detail.error.unknown — that's the gap the
    // round-2 fix closes.
    useAssignCleaningTaskMock.mockReturnValue(
      makeMutation({
        isError: true,
        isSuccess: false,
        submittedAt: 1,
        error: new ApiError({
          status: 403,
          code: "forbidden",
          message: "x",
        }),
      }),
    );
    renderView();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("No tienes permiso para asignar limpiezas");
    expect(alert.textContent).not.toContain("Ha ocurrido un error inesperado");
  });

  describe("CleaningTaskDetailView — tabs wiring (R2.1, R2.2, R2.5, D4)", () => {
    const contentTab = () =>
      screen.getByRole("tab", { name: esCleaning.tabs.content });
    const messagesTab = () =>
      screen.getByRole("tab", { name: esCleaning.messages.tab });

    beforeEach(() => {
      getTaskMessagesMock.mockReset().mockResolvedValue({
        data: [],
        total: 0,
        page: 1,
        perPage: 20,
        totalPages: 0,
      });
    });

    it("opens on the operational content tab, and asks for no thread until the tab is touched (R2.1, D4)", () => {
      renderView();
      expect(contentTab()).toHaveAttribute("aria-selected", "true");
      expect(messagesTab()).toHaveAttribute("aria-selected", "false");
      expect(getTaskMessagesMock).not.toHaveBeenCalled();
    });

    it("requests the first page and shows the thread once the tab is opened (R2.2)", async () => {
      renderView();
      fireEvent.click(messagesTab());
      await waitFor(() =>
        expect(getTaskMessagesMock).toHaveBeenCalledWith(
          "tenant-1",
          "task-1",
          1,
        ),
      );
      expect(
        await screen.findByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument();
      expect(
        screen.getByLabelText(esCleaning.messages.composer.label),
      ).toBeInTheDocument();
    });

    it("hides the operational panel instead of unmounting it (R2.1)", () => {
      renderView();
      fireEvent.click(messagesTab());
      const contentPanel = document.getElementById(
        "manager-cleaning-panel-content",
      );
      expect(contentPanel).toHaveAttribute("hidden");
    });

    /**
     * R2.5 with the real wrapper rather than the panel in isolation: the
     * messages read 404s, the wrapper's `messagesNotFound` flips, the whole
     * detail screen — tabs included — is replaced by the same not-found
     * EmptyState the task read already produces.
     */
    it("replaces the whole screen with the not-found EmptyState when the messages read 404s (R2.5)", async () => {
      getTaskMessagesMock.mockRejectedValue(
        new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
      );
      renderView();

      fireEvent.click(messagesTab());

      await waitFor(() => {
        expect(screen.queryByRole("tablist")).toBeNull();
      });
      expect(screen.getByText(esCleaning.detail.notFound)).toBeInTheDocument();
      expect(
        screen.getByText(esCleaning.detail.context.backToList),
      ).toHaveAttribute("href", "/cleaning");
    });
  });
});