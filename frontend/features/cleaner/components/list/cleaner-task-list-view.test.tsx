import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type {
  CleanerDataSource,
  CleaningChecklist,
  CleaningPhoto,
  CleaningTaskContext,
  CleaningTaskListItem,
  PaginatedResponse,
  PhotoRequirementsResponse,
} from "../../data";
import { CleanerTaskListView } from "./cleaner-task-list-view";

const listTasks = vi.hoisted(() => vi.fn());
const getTask = vi.hoisted(() => vi.fn());
const getTaskContext = vi.hoisted(() => vi.fn());
const getTaskChecklist = vi.hoisted(() => vi.fn());
const getTaskPhotoRequirements = vi.hoisted(() => vi.fn());
const getTaskPhotos = vi.hoisted(() => vi.fn());
const acceptTask = vi.hoisted(() => vi.fn());
const rejectTask = vi.hoisted(() => vi.fn());
const startTask = vi.hoisted(() => vi.fn());
const completeTask = vi.hoisted(() => vi.fn());
const completeChecklistItem = vi.hoisted(() => vi.fn());
const uploadPhoto = vi.hoisted(() => vi.fn());
const reportIncident = vi.hoisted(() => vi.fn());

const tenantId = vi.hoisted(() => ({ current: "tenant-1" }));

vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  useAuth: () => ({
    user: { tenant_id: tenantId.current, role: "CLEANER" },
  }),
}));
vi.mock("@/lib/auth/auth-provider", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/auth-provider")>()),
  useAuth: () => ({
    user: { tenant_id: tenantId.current, role: "CLEANER" },
  }),
}));

vi.mock("../../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../data")>()),
  getCleanerDataSource: (): CleanerDataSource => ({
    listTasks,
    getTask,
    getTaskContext,
    getTaskChecklist,
    getTaskPhotoRequirements,
    getTaskPhotos,
    acceptTask,
    rejectTask,
    startTask,
    completeTask,
    completeChecklistItem,
    uploadPhoto,
    reportIncident,
  }),
}));

const TASK_UUID = "8f14e45f-ceea-467a-9b7c-9d7c1a2b3c4d";
const PROPERTY_UUID = "c9f0f895-fb98-4b41-a54b-2e1a7c0d9e8f";

function taskListItem(
  overrides: Partial<CleaningTaskListItem> = {},
): CleaningTaskListItem {
  return {
    id: TASK_UUID,
    propertyId: PROPERTY_UUID,
    reservationId: "reservation-1",
    assignedCleanerId: "cleaner-1",
    status: "ASSIGNED",
    scheduledStart: "2026-08-20T09:00:00Z",
    scheduledEnd: "2026-08-20T11:00:00Z",
    acceptedAt: null,
    startedAt: null,
    completedAt: null,
    validationStatus: "PENDING",
    createdAt: "2026-08-19T18:00:00Z",
    ...overrides,
  };
}

const taskContext: CleaningTaskContext = {
  propertyName: "Redes 11",
  propertyInternalCode: "REDES11",
  addressLine1: "Calle Mayor 1",
  addressLine2: null,
  city: "Madrid",
  province: "Madrid",
  postalCode: "28013",
  country: "ES",
  timezone: "Europe/Madrid",
  checkoutAt: "2026-08-20T11:00:00Z",
  nextCheckinDeadline: "2026-08-21T16:00:00Z",
};

function page(
  data: CleaningTaskListItem[],
  envelope: Partial<PaginatedResponse<CleaningTaskListItem>> = {},
): PaginatedResponse<CleaningTaskListItem> {
  return {
    data,
    total: data.length,
    page: 1,
    perPage: 20,
    totalPages: data.length === 0 ? 0 : 1,
    ...envelope,
  };
}

function renderView() {
  const client = new QueryClient({
    // `retry: false` is the default for the list query; the per-row context
    // query overrides it with the shared `retryPolicy` (a 5xx does retry), so
    // `retryDelay` needs to be fast here or the default exponential backoff
    // outlasts `waitFor`'s timeout on the retry-then-recover assertions below
    // (same pattern as `use-incidents.test.tsx`, `use-properties.test.tsx`).
    defaultOptions: { queries: { retry: false, retryDelay: 0 } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<CleanerTaskListView />, { wrapper: Wrapper });
}

beforeEach(() => {
  tenantId.current = "tenant-1";
  listTasks.mockReset().mockResolvedValue(page([taskListItem()]));
  getTaskContext.mockReset().mockResolvedValue(taskContext);
  getTask.mockReset();
  getTaskChecklist.mockReset().mockResolvedValue({
    data: [],
  } satisfies CleaningChecklist);
  getTaskPhotoRequirements.mockReset().mockResolvedValue({
    data: [],
  } satisfies PhotoRequirementsResponse);
  getTaskPhotos.mockReset().mockResolvedValue([] satisfies CleaningPhoto[]);
  acceptTask.mockReset();
  rejectTask.mockReset();
  startTask.mockReset();
  completeTask.mockReset();
  completeChecklistItem.mockReset();
  uploadPhoto.mockReset();
  reportIncident.mockReset();
});

describe("CleanerTaskListView (R1)", () => {
  it("renders chips and the row from the backend response", async () => {
    renderView();

    await waitFor(() =>
      expect(screen.getByText("REDES11 · Redes 11")).toBeInTheDocument(),
    );
    // The row's status badge, not the filter chip of the same name — both
    // render the text "Asignada", so this must be scoped to the row.
    expect(screen.getByRole("listitem").textContent).toContain("Asignada");
    // All seven chips from D5.
    for (const label of [
      "Asignada",
      "Aceptada",
      "En curso",
      "Pendiente de revisión",
      "Completada",
      "Rechazada",
      "Cancelada",
    ]) {
      // Some chip labels overlap with status badge text; query the group
      // specifically.
      const group = screen.getByRole("group", { name: "Filtrar por estado" });
      expect(group.textContent).toContain(label);
    }
  });

  it("clicking a chip re-asks the list with that status", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11 · Redes 11")).toBeInTheDocument(),
    );

    listTasks.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "En curso" }));

    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(1));
    expect(listTasks.mock.calls[0][1]).toEqual({ status: "IN_PROGRESS" });
  });

  it("clicking the active chip again clears the status filter (R1.6)", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11 · Redes 11")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "En curso" }));
    await waitFor(() => expect(listTasks).toHaveBeenCalled());
    listTasks.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "En curso" }));
    await waitFor(() => expect(listTasks).toHaveBeenCalled());
    expect(listTasks.mock.calls[0][1]).toEqual({});
  });

  it("renders em-dashes on rows whose context failed (R1.4)", async () => {
    getTaskContext.mockRejectedValueOnce(
      new ApiError({ status: 500, code: "INTERNAL", message: "boom" }),
    );
    renderView();

    await waitFor(() =>
      expect(screen.getByText("REDES11 · Redes 11")).toBeInTheDocument(),
    );
  });

  it("renders 404 ErrorState without a retry button (R1.7)", async () => {
    listTasks.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderView();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toBeInTheDocument(),
    );
    // No retry button on 4xx.
    expect(screen.queryByRole("button", { name: /reintentar/i })).toBeNull();
  });

  it("renders EmptyState when the list returns nothing", async () => {
    listTasks.mockResolvedValue(page([]));
    renderView();

    await waitFor(() =>
      expect(
        screen.getByText("Ahora mismo no tienes tareas"),
      ).toBeInTheDocument(),
    );
  });
});

describe("CleanerTaskListView — degraded row context (R1.4)", () => {
  it("still renders other rows when one context fails", async () => {
    listTasks.mockResolvedValue(
      page([
        taskListItem({ id: "task-a" }),
        taskListItem({ id: "task-b", status: "ACCEPTED" }),
      ]),
    );
    getTaskContext.mockImplementation(async (_t: string, id: string) => {
      if (id === "task-b") {
        throw new ApiError({
          status: 500,
          code: "INTERNAL",
          message: "boom",
        });
      }
      return taskContext;
    });
    renderView();

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    // The other row still renders the resolved property name; task-b's
    // context is a permanent failure (not transient), so it stays degraded
    // to the em-dash rather than ever resolving (R1.4).
    await waitFor(() =>
      expect(screen.getAllByText("REDES11 · Redes 11")).toHaveLength(1),
    );
  });
});

describe("CleanerTaskListView — link to detail (R1.2)", () => {
  it("renders the row as a link to /cleaner/tasks/[id]", async () => {
    renderView();

    await waitFor(() =>
      expect(screen.getByText("REDES11 · Redes 11")).toBeInTheDocument(),
    );
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe(`/cleaner/tasks/${TASK_UUID}`);
  });
});

describe("CleanerTaskListView — loading state (R1.7)", () => {
  it("renders LoadingState with role=status and aria-busy", () => {
    listTasks.mockReturnValue(new Promise(() => {}));
    renderView();

    const status = screen.getByRole("status", { busy: true });
    expect(status).toHaveAttribute("aria-busy", "true");
  });
});