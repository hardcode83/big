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
  CleaningTask,
  CleaningTaskContext,
  PhotoRequirementsResponse,
} from "../../data";
import { CleanerTaskDetailView } from "./cleaner-task-detail-view";

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

const task: CleaningTask = {
  id: "task-1",
  propertyId: "property-1",
  reservationId: "reservation-1",
  assignedCleanerId: "cleaner-1",
  status: "ASSIGNED",
  scheduledStart: null,
  scheduledEnd: null,
  acceptedAt: null,
  startedAt: null,
  completedAt: null,
  validationStatus: "PENDING",
  createdAt: "2026-08-19T18:00:00Z",
};

const context: CleaningTaskContext = {
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
  nextCheckinDeadline: null,
};

const checklist: CleaningChecklist = {
  data: [
    {
      itemId: "kitchen",
      label: "Limpiar la cocina",
      required: true,
      completed: false,
      completedAt: null,
      completedBy: null,
    },
  ],
};

const requirements: PhotoRequirementsResponse = {
  data: [
    {
      photoType: "kitchen",
      label: "Cocina",
      required: true,
      uploaded: false,
    },
  ],
};

const photo: CleaningPhoto = {
  id: "photo-1",
  cleaningTaskId: "task-1",
  photoType: "kitchen",
  uploadedBy: "cleaner-1",
  createdAt: "2026-08-20T10:00:00Z",
  url: "https://example.com/photo",
};

function renderView() {
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
  return render(<CleanerTaskDetailView taskId="task-1" />, { wrapper: Wrapper });
}

beforeEach(() => {
  tenantId.current = "tenant-1";
  routerReplace.mockReset();
  getTask.mockReset().mockResolvedValue(task);
  getTaskContext.mockReset().mockResolvedValue(context);
  getTaskChecklist.mockReset().mockResolvedValue(checklist);
  getTaskPhotoRequirements.mockReset().mockResolvedValue(requirements);
  getTaskPhotos.mockReset().mockResolvedValue([photo]);
  for (const mock of [
    listTasks,
    acceptTask,
    rejectTask,
    startTask,
    completeTask,
    completeChecklistItem,
    uploadPhoto,
    reportIncident,
  ]) {
    mock.mockReset();
  }
});

describe("CleanerTaskDetailView (R2.1, R2.8)", () => {
  it("mounts all five reads in parallel", async () => {
    renderView();
    await waitFor(() => expect(getTask).toHaveBeenCalled());
    expect(getTask).toHaveBeenCalledWith("tenant-1", "task-1");
    expect(getTaskContext).toHaveBeenCalledWith("tenant-1", "task-1");
    expect(getTaskChecklist).toHaveBeenCalledWith("tenant-1", "task-1");
    expect(getTaskPhotoRequirements).toHaveBeenCalledWith(
      "tenant-1",
      "task-1",
    );
    expect(getTaskPhotos).toHaveBeenCalledWith("tenant-1", "task-1");
  });

  it("renders the context block, checklist and gallery", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );
    expect(screen.getByText("Limpiar la cocina")).toBeInTheDocument();
    expect(screen.getByText("Cocina")).toBeInTheDocument();
  });

  it("renders the action bar reflecting the task's status via CLEANER_ACTIONS", async () => {
    getTask.mockResolvedValue({ ...task, status: "ASSIGNED" });
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Aceptar" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rechazar" }),
    ).toBeInTheDocument();
  });

  it("renders the empty + back state on 404 (R2.8)", async () => {
    getTask.mockRejectedValueOnce(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderView();

    await waitFor(() =>
      expect(screen.getByText(/Tarea no disponible/)).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Volver a mis tareas" }),
    ).toBeInTheDocument();
  });

  it("renders the completion panel after the close fires (R7.2)", async () => {
    getTask.mockResolvedValue({ ...task, status: "IN_PROGRESS" });
    completeTask.mockResolvedValueOnce({ ...task, status: "PENDING_REVIEW" });
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Cerrar limpieza" }));
    await waitFor(() =>
      expect(screen.getByText("Limpieza cerrada")).toBeInTheDocument(),
    );
    // Reversible, not a redirect: the panel's own button navigates, the close
    // itself does not (R7.2, D8).
    expect(routerReplace).not.toHaveBeenCalled();
  });
});