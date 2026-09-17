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
  CleaningTaskMessage,
  PaginatedResponse,
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
const getTaskMessages = vi.hoisted(() => vi.fn());
const sendTaskMessage = vi.hoisted(() => vi.fn());

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
    getTaskMessages,
    sendTaskMessage,
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

const messagesPage: PaginatedResponse<CleaningTaskMessage> = {
  data: [
    {
      id: "message-1",
      authorId: "manager-1",
      authorRole: "PROPERTY_MANAGER",
      content: "Deja la llave en el buzón",
      createdAt: "2026-08-20T09:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  perPage: 20,
  totalPages: 1,
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
  getTaskMessages.mockReset().mockResolvedValue(messagesPage);
  for (const mock of [
    listTasks,
    acceptTask,
    rejectTask,
    startTask,
    completeTask,
    completeChecklistItem,
    uploadPhoto,
    reportIncident,
    sendTaskMessage,
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

  it("replaces the whole screen with the not-found EmptyState when the messages read 404s (R4.3)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("tab", { name: "Mensajes" }));

    // The whole detail screen — tabs included — is replaced by the same
    // "tarea no disponible" EmptyState the other five parallel reads already
    // produce: no tablist, no leftover content tab underneath. Waiting on the
    // tablist's disappearance (rather than just the title text) is what pins
    // this to the whole-screen swap. The panel itself renders nothing while a
    // parent is listening, so this title only ever comes from the swap.
    await waitFor(() => {
      expect(screen.queryByRole("tablist")).toBeNull();
    });
    expect(screen.getByText("Tarea no disponible")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Volver a mis tareas" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("REDES11")).toBeNull();
  });

  it("opens on the content tab and does not request the thread yet (R3.1, D1)", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );
    expect(screen.getByRole("tab", { name: "Tarea" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Mensajes" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(getTaskMessages).not.toHaveBeenCalled();
  });

  it("loads the thread when the messages tab is opened (R1.1)", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Mensajes" }));
    await waitFor(() =>
      expect(getTaskMessages).toHaveBeenCalledWith("tenant-1", "task-1", 1),
    );
    expect(
      await screen.findByText("Deja la llave en el buzón"),
    ).toBeInTheDocument();
  });

  it("keeps the content panel mounted across a round trip to messages (R3.2)", async () => {
    getTask.mockResolvedValue({ ...task, status: "IN_PROGRESS" });
    renderView();
    await waitFor(() =>
      expect(screen.getByText("REDES11")).toBeInTheDocument(),
    );
    // The incident report form is the content tab's stateful child: opened
    // here, it must still be open after visiting the messages tab.
    fireEvent.click(
      screen.getByTestId("cleaner-incident-report-trigger"),
    );
    expect(screen.getByLabelText("Título")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Mensajes" }));
    fireEvent.click(screen.getByRole("tab", { name: "Tarea" }));

    expect(screen.getByLabelText("Título")).toBeInTheDocument();
    expect(screen.getByText("REDES11")).toBeVisible();
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