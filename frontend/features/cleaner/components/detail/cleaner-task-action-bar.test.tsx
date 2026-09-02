import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type {
  CleanerDataSource,
  CleaningChecklist,
  CleaningTask,
  PhotoRequirementsResponse,
} from "../../data";
import { CleanerTaskActionBar } from "./cleaner-task-action-bar";

const acceptTask = vi.hoisted(() => vi.fn());
const rejectTask = vi.hoisted(() => vi.fn());
const startTask = vi.hoisted(() => vi.fn());
const completeTask = vi.hoisted(() => vi.fn());
const completeChecklistItem = vi.hoisted(() => vi.fn());
const uploadPhoto = vi.hoisted(() => vi.fn());
const reportIncident = vi.hoisted(() => vi.fn());
const listTasks = vi.hoisted(() => vi.fn());
const getTask = vi.hoisted(() => vi.fn());
const getTaskContext = vi.hoisted(() => vi.fn());
const getTaskChecklist = vi.hoisted(() => vi.fn());
const getTaskPhotoRequirements = vi.hoisted(() => vi.fn());
const getTaskPhotos = vi.hoisted(() => vi.fn());

const tenantId = vi.hoisted(() => ({ current: "tenant-1" }));
const routerReplace = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace }),
}));

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

const baseTask: CleaningTask = {
  id: "task-1",
  propertyId: "property-1",
  reservationId: "reservation-1",
  assignedCleanerId: "cleaner-1",
  status: "IN_PROGRESS",
  scheduledStart: null,
  scheduledEnd: null,
  acceptedAt: "2026-08-20T09:00:00Z",
  startedAt: "2026-08-20T10:00:00Z",
  completedAt: null,
  validationStatus: "PENDING",
  createdAt: "2026-08-19T18:00:00Z",
};

const checklist: CleaningChecklist = { data: [] };
const requirements: PhotoRequirementsResponse = { data: [] };

function renderBar(task: CleaningTask) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(
    <CleanerTaskActionBar
      task={task}
      checklist={checklist}
      requirements={requirements}
    />,
    { wrapper: Wrapper },
  );
}

beforeEach(() => {
  tenantId.current = "tenant-1";
  routerReplace.mockReset();
  for (const mock of [
    acceptTask,
    rejectTask,
    startTask,
    completeTask,
    completeChecklistItem,
    uploadPhoto,
    reportIncident,
    listTasks,
    getTask,
    getTaskContext,
    getTaskChecklist,
    getTaskPhotoRequirements,
    getTaskPhotos,
  ]) {
    mock.mockReset().mockResolvedValue({});
  }
});

describe("CleanerTaskActionBar (R3.1, R6.1, R7.1)", () => {
  it("ASSIGNED row shows accept + reject", () => {
    renderBar({ ...baseTask, status: "ASSIGNED" });
    expect(
      screen.getByRole("button", { name: "Aceptar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rechazar" }),
    ).toBeInTheDocument();
  });

  it("ACCEPTED row shows start", () => {
    renderBar({ ...baseTask, status: "ACCEPTED" });
    expect(
      screen.getByRole("button", { name: "Iniciar" }),
    ).toBeInTheDocument();
  });

  it("IN_PROGRESS row shows close + report incident", () => {
    renderBar({ ...baseTask, status: "IN_PROGRESS" });
    expect(
      screen.getByRole("button", { name: "Cerrar limpieza" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    ).toBeInTheDocument();
  });

  it.each([
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
    "PENDING_REVIEW",
    "FAILED",
  ] as const)(
    "%s shows the localized explanation, no buttons",
    (status) => {
      renderBar({ ...baseTask, status });
      expect(screen.queryByRole("button", { name: "Aceptar" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Rechazar" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Iniciar" })).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Cerrar limpieza" }),
      ).toBeNull();
      // Some explanation text exists.
      expect(screen.getByText(/Esta/)).toBeInTheDocument();
    },
  );

  it("reject calls router.replace('/cleaner') (R3.3)", async () => {
    rejectTask.mockResolvedValueOnce(baseTask);
    renderBar({ ...baseTask, status: "ASSIGNED" });

    fireEvent.click(screen.getByRole("button", { name: "Rechazar" }));
    await waitFor(() => expect(rejectTask).toHaveBeenCalled());
    expect(routerReplace).toHaveBeenCalledWith("/cleaner");
  });

  it("close 409 surfaces the missing-required-items copy (R7.3)", async () => {
    completeTask.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "CONFLICT",
        message: "missing required items",
      }),
    );
    const checklistWithPending: CleaningChecklist = {
      data: [
        {
          itemId: "kitchen",
          label: "Cocina",
          required: true,
          completed: false,
          completedAt: null,
          completedBy: null,
        },
      ],
    };
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>
          <I18nProvider locale="es">{children}</I18nProvider>
        </QueryClientProvider>
      );
    }
    render(
      <CleanerTaskActionBar
        task={baseTask}
        checklist={checklistWithPending}
        requirements={requirements}
      />,
      { wrapper: Wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Cerrar limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByText(/Faltan ítems obligatorios/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/missing required items/)).toBeNull();
  });

  it("close 409 with critical-incident never names the incident (R7.3)", async () => {
    completeTask.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "CONFLICT",
        message: "critical incident on property",
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>
          <I18nProvider locale="es">{children}</I18nProvider>
        </QueryClientProvider>
      );
    }
    render(
      <CleanerTaskActionBar
        task={baseTask}
        checklist={{ data: [] }}
        requirements={{ data: [] }}
      />,
      { wrapper: Wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Cerrar limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByText(/incidencia crítica sin resolver/),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/critical incident on property/)).toBeNull();
  });
});