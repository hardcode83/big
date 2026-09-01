import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type {
  CleanerDataSource,
  CleaningIncidentReportAck,
} from "../../data";
import { CleanerIncidentReportPanel } from "./cleaner-incident-report-panel";

const reportIncident = vi.hoisted(() => vi.fn());
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

const ack: CleaningIncidentReportAck = {
  id: "incident-1",
  status: "OPEN",
  createdAt: "2026-08-20T10:00:00Z",
};

function renderPanel(status: string) {
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
    <CleanerIncidentReportPanel taskId="task-1" status={status} />,
    { wrapper: Wrapper },
  );
}

beforeEach(() => {
  tenantId.current = "tenant-1";
  reportIncident.mockReset().mockResolvedValue(ack);
});

describe("CleanerIncidentReportPanel (R6)", () => {
  it("renders the trigger button in IN_PROGRESS (R6.1)", () => {
    renderPanel("IN_PROGRESS");
    expect(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    ).toBeInTheDocument();
  });

  it.each(["COMPLETED", "REJECTED", "CANCELLED", "PENDING_REVIEW"])(
    "does not render the trigger button when status is %s (R6.1)",
    (status) => {
      renderPanel(status);
      expect(
        screen.queryByRole("button", { name: "Reportar incidencia" }),
      ).toBeNull();
    },
  );

  it("empty title blocks submission (R6.2)", async () => {
    renderPanel("IN_PROGRESS");
    fireEvent.click(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    );
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Sale agua" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar incidencia" }));
    await waitFor(() =>
      expect(reportIncident).not.toHaveBeenCalled(),
    );
    expect(screen.getByText("Indica un título.")).toBeInTheDocument();
  });

  it("title of 301 characters blocks submission (R6.2)", async () => {
    renderPanel("IN_PROGRESS");
    fireEvent.click(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    );
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "a".repeat(301) },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Sale agua" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar incidencia" }));
    await waitFor(() =>
      expect(reportIncident).not.toHaveBeenCalled(),
    );
    expect(
      screen.getByText(/no puede pasar de 300 caracteres/),
    ).toBeInTheDocument();
  });

  it("description of 5001 characters blocks submission (R6.2)", async () => {
    renderPanel("IN_PROGRESS");
    fireEvent.click(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    );
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "Caldera rota" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "a".repeat(5001) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar incidencia" }));
    await waitFor(() =>
      expect(reportIncident).not.toHaveBeenCalled(),
    );
    expect(
      screen.getByText(/no puede pasar de 5000 caracteres/),
    ).toBeInTheDocument();
  });

  it("on 409 surfaces a localized message and refreshes the task (R6.5)", async () => {
    reportIncident.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "CONFLICT",
        message: "task is terminal",
      }),
    );
    renderPanel("IN_PROGRESS");
    fireEvent.click(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    );
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "Caldera rota" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Sale agua por debajo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar incidencia" }));
    await waitFor(() => expect(reportIncident).toHaveBeenCalled());
    expect(
      screen.getByText(/La tarea ha cambiado de estado/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/task is terminal/)).toBeNull();
  });

  it("on 201 renders the ack and never the original inputs (R6.3)", async () => {
    renderPanel("IN_PROGRESS");
    fireEvent.click(
      screen.getByRole("button", { name: "Reportar incidencia" }),
    );
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "Caldera rota" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Sale agua por debajo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Enviar incidencia" }));
    await waitFor(() =>
      expect(screen.getByText("Incidencia registrada")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Caldera rota")).toBeNull();
    expect(screen.queryByText("Sale agua por debajo")).toBeNull();
    expect(screen.getByText(ack.id)).toBeInTheDocument();
    expect(screen.getByText(ack.status)).toBeInTheDocument();
  });
});