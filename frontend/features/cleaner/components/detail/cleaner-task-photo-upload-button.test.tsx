import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type { CleanerDataSource, PhotoRequirementState } from "../../data";
import { CleanerTaskPhotoUploadButton } from "./cleaner-task-photo-upload-button";

const uploadPhoto = vi.hoisted(() => vi.fn());
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

const entry: PhotoRequirementState = {
  photoType: "kitchen",
  label: "Cocina",
  required: true,
  uploaded: false,
};

function renderButton() {
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
    <CleanerTaskPhotoUploadButton taskId="task-1" entry={entry} />,
    { wrapper: Wrapper },
  );
}

beforeEach(() => {
  tenantId.current = "tenant-1";
  uploadPhoto.mockReset().mockResolvedValue({
    id: "photo-1",
    cleaningTaskId: "task-1",
    photoType: "kitchen",
    uploadedBy: "cleaner-1",
    createdAt: "2026-08-20T10:00:00Z",
    url: "https://example.com/photo",
  });
});

describe("CleanerTaskPhotoUploadButton (R5.1, R5.2, R5.3, R5.5)", () => {
  it("renders the upload button", () => {
    renderButton();
    expect(
      screen.getByRole("button", { name: "Subir foto" }),
    ).toBeInTheDocument();
  });

  it("selecting a file calls uploadPhoto with photo_type from the entry (R5.3)", async () => {
    renderButton();

    const file = new File(["bytes"], "kitchen.jpg", { type: "image/jpeg" });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(uploadPhoto).toHaveBeenCalled());
    expect(uploadPhoto).toHaveBeenCalledWith(
      tenantId.current,
      "task-1",
      "kitchen",
      expect.any(File),
    );
  });

  it("renders the JPEG/PNG/WebP message on a 422 (R5.5)", async () => {
    uploadPhoto.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "heic not allowed",
      }),
    );
    renderButton();

    const file = new File(["bytes"], "kitchen.heic", { type: "image/heic" });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(
        screen.getByText(/JPEG, PNG y WebP/),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/heic not allowed/)).toBeNull();
  });

  it("renders the tooLarge message on a 413", async () => {
    uploadPhoto.mockRejectedValueOnce(
      new ApiError({
        status: 413,
        code: "PAYLOAD_TOO_LARGE",
        message: "10MB exceeded",
      }),
    );
    renderButton();

    const file = new File(["big"], "big.jpg", { type: "image/jpeg" });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByText(/pesa demasiado/)).toBeInTheDocument(),
    );
  });

  it("renders the storage message on a 502", async () => {
    uploadPhoto.mockRejectedValueOnce(
      new ApiError({
        status: 502,
        code: "STORAGE_UNAVAILABLE",
        message: "S3 down",
      }),
    );
    renderButton();

    const file = new File(["bytes"], "kitchen.jpg", { type: "image/jpeg" });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(screen.getByText(/guardar la foto/)).toBeInTheDocument(),
    );
  });

  it("renders the conflict message on a 409 (R5.5)", async () => {
    uploadPhoto.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        code: "CONFLICT",
        message: "not in progress",
      }),
    );
    renderButton();

    const file = new File(["bytes"], "kitchen.jpg", { type: "image/jpeg" });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() =>
      expect(
        screen.getByText(/La tarea ha cambiado de estado/),
      ).toBeInTheDocument(),
    );
  });

  it("does not retry on any 4xx/5xx (R5.5)", async () => {
    uploadPhoto.mockRejectedValueOnce(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "nope",
      }),
    );
    renderButton();

    const file = new File(["bytes"], "kitchen.jpg", { type: "image/jpeg" });
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(uploadPhoto).toHaveBeenCalledTimes(1));
  });
});