import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type {
  CleanerDataSource,
  CleaningChecklistItem,
} from "../../data";
import { CleanerTaskChecklistItem } from "./cleaner-task-checklist-item";

const completeChecklistItem = vi.hoisted(() => vi.fn());
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

const item: CleaningChecklistItem = {
  itemId: "kitchen",
  label: "Limpiar la cocina",
  required: true,
  completed: false,
  completedAt: null,
  completedBy: null,
};

function renderItem() {
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
  return render(<CleanerTaskChecklistItem taskId="task-1" item={item} />, {
    wrapper: Wrapper,
  });
}

beforeEach(() => {
  tenantId.current = "tenant-1";
  completeChecklistItem.mockReset().mockResolvedValue(item);
});

describe("CleanerTaskChecklistItem (R4.1, R4.3, R4.4)", () => {
  it("renders the button", () => {
    renderItem();
    expect(
      screen.getByRole("button", { name: "Marcar como hecho" }),
    ).toBeInTheDocument();
  });

  it("does not render the button for a completed item (R4.2)", () => {
    render(
      <CleanerTaskChecklistItem
        taskId="task-1"
        item={{ ...item, completed: true }}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Marcar como hecho" }),
    ).toBeNull();
  });

  it("clicking the button calls completeChecklistItem", async () => {
    renderItem();

    fireEvent.click(
      screen.getByRole("button", { name: "Marcar como hecho" }),
    );

    await waitFor(() => expect(completeChecklistItem).toHaveBeenCalled());
    expect(completeChecklistItem).toHaveBeenCalledWith(
      tenantId.current,
      "task-1",
      "kitchen",
    );
  });

  it("on 404, surfaces a localized message and refreshes the checklist (R4.3)", async () => {
    completeChecklistItem.mockRejectedValueOnce(
      new ApiError({
        status: 404,
        code: "NOT_FOUND",
        message: "stale item",
      }),
    );
    renderItem();

    fireEvent.click(
      screen.getByRole("button", { name: "Marcar como hecho" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Este ítem ya no pertenece a la plantilla/),
      ).toBeInTheDocument();
    });
    // The localized copy comes from `mapCleanerError`, not the envelope.
    expect(screen.queryByText(/stale item/)).toBeNull();
  });

  it("on 409, surfaces a localized conflict message (R4.4)", async () => {
    completeChecklistItem.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "CONFLICT",
        message: "not in progress",
      }),
    );
    renderItem();

    fireEvent.click(
      screen.getByRole("button", { name: "Marcar como hecho" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/La tarea ha cambiado de estado/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/not in progress/)).toBeNull();
  });
});