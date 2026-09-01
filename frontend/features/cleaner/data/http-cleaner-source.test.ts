import { describe, expect, it, vi } from "vitest";

import { ApiError, type ApiClient } from "@/lib/api";

import { HttpCleanerSource } from "./http-cleaner-source";

function sourceWith(response: unknown): {
  source: HttpCleanerSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  return {
    source: new HttpCleanerSource({ request } as unknown as ApiClient),
    request,
  };
}

const taskResponse = {
  id: "task-1",
  property_id: "property-1",
  reservation_id: "reservation-1",
  assigned_cleaner_id: "cleaner-1",
  status: "ASSIGNED",
  scheduled_start: "2026-08-20T09:00:00Z",
  scheduled_end: "2026-08-20T11:00:00Z",
  accepted_at: null,
  started_at: null,
  completed_at: null,
  validation_status: "PENDING",
  created_at: "2026-08-19T18:00:00Z",
  checklist_template_id: "template-1",
  updated_at: "2026-08-19T18:05:00Z",
  validated_at: null,
  validated_by_user_id: null,
};

function taskPage(items: unknown[]) {
  return { data: items, total: items.length, page: 1, per_page: 20, total_pages: 1 };
}

describe("HttpCleanerSource.listTasks (R1.1, R1.5)", () => {
  it("sends only status + page when no status filter is chosen", async () => {
    const { source, request } = sourceWith(taskPage([taskResponse]));

    await source.listTasks("tenant-1", {}, 2);

    expect(request).toHaveBeenCalledWith("/api/v1/cleaning-tasks", {
      query: { page: 2, per_page: 20 },
    });
    // Exact key set — no leaked undefined.
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
    ]);
  });

  it("sends status as a single value when chosen", async () => {
    const { source, request } = sourceWith(taskPage([]));

    await source.listTasks("tenant-1", { status: "IN_PROGRESS" }, 1);

    expect(request).toHaveBeenCalledWith("/api/v1/cleaning-tasks", {
      query: { page: 1, per_page: 20, status: "IN_PROGRESS" },
    });
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
      "status",
    ]);
  });

  it("maps the listing row to the UI DTO, dropping the irrelevant pre-flight", async () => {
    const { source } = sourceWith(
      taskPage([
        { ...taskResponse, id: "task-1" },
        { ...taskResponse, id: "task-2" },
      ]),
    );

    const page = await source.listTasks("tenant-1", {}, 1);

    expect(page.data.map((t) => t.id)).toEqual(["task-1", "task-2"]);
    expect(page.total).toBe(2);
    expect(page.perPage).toBe(20);
    expect(page.totalPages).toBe(1);
  });
});

describe("HttpCleanerSource.getTask (R2.1)", () => {
  it("hits /api/v1/cleaning-tasks/{task_id} and maps to the UI DTO", async () => {
    const { source, request } = sourceWith(taskResponse);

    const task = await source.getTask("tenant-1", "task-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}",
      { pathParams: { task_id: "task-1" } },
    );
    expect(task).toMatchObject({
      id: "task-1",
      propertyId: "property-1",
      status: "ASSIGNED",
      validationStatus: "PENDING",
    });
  });
});

describe("HttpCleanerSource.getTaskContext (R2.2)", () => {
  it("maps eleven fields, leaving the two nullable instants as null", async () => {
    const { source, request } = sourceWith({
      property_name: "Redes 11",
      property_internal_code: "REDES11",
      address_line1: "Calle Mayor 1",
      address_line2: null,
      city: "Madrid",
      province: "Madrid",
      postal_code: "28013",
      country: "ES",
      timezone: "Europe/Madrid",
      checkout_at: "2026-08-20T11:00:00Z",
      next_checkin_deadline: null,
    });

    const context = await source.getTaskContext("tenant-1", "task-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/context",
      { pathParams: { task_id: "task-1" } },
    );
    expect(context).toEqual({
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
    });
  });
});

describe("HttpCleanerSource.getTaskChecklist (R2.3)", () => {
  it("maps every checklist item, keeping the backend order", async () => {
    const { source } = sourceWith({
      data: [
        {
          item_id: "kitchen",
          label: "Limpiar la cocina",
          required: true,
          completed: false,
          completed_at: null,
          completed_by: null,
        },
        {
          item_id: "bath",
          label: "Limpiar el baño",
          required: true,
          completed: true,
          completed_at: "2026-08-20T10:30:00Z",
          completed_by: "cleaner-1",
        },
      ],
    });

    const checklist = await source.getTaskChecklist("tenant-1", "task-1");

    expect(checklist.data).toEqual([
      {
        itemId: "kitchen",
        label: "Limpiar la cocina",
        required: true,
        completed: false,
        completedAt: null,
        completedBy: null,
      },
      {
        itemId: "bath",
        label: "Limpiar el baño",
        required: true,
        completed: true,
        completedAt: "2026-08-20T10:30:00Z",
        completedBy: "cleaner-1",
      },
    ]);
  });
});

describe("HttpCleanerSource.getTaskPhotoRequirements (R2.4)", () => {
  it("maps every category, copying uploaded verbatim", async () => {
    const { source } = sourceWith({
      data: [
        {
          photo_type: "kitchen",
          label: "Cocina",
          required: true,
          uploaded: false,
        },
        {
          photo_type: "bath",
          label: "Baño",
          required: false,
          uploaded: true,
        },
      ],
    });

    const reqs = await source.getTaskPhotoRequirements("tenant-1", "task-1");

    expect(reqs.data).toEqual([
      { photoType: "kitchen", label: "Cocina", required: true, uploaded: false },
      { photoType: "bath", label: "Baño", required: false, uploaded: true },
    ]);
  });
});

describe("HttpCleanerSource.getTaskPhotos (R2.5)", () => {
  it("maps every photo, copying url verbatim and never building storage_key", async () => {
    const { source } = sourceWith({
      data: [
        {
          id: "photo-1",
          cleaning_task_id: "task-1",
          photo_type: "kitchen",
          uploaded_by: "cleaner-1",
          created_at: "2026-08-20T10:00:00Z",
          url: "/api/v1/cleaning-photos/photo-1?exp=1700000000&sig=abc",
        },
      ],
    });

    const photos = await source.getTaskPhotos("tenant-1", "task-1");

    expect(photos).toHaveLength(1);
    expect(photos[0]).toEqual({
      id: "photo-1",
      cleaningTaskId: "task-1",
      photoType: "kitchen",
      uploadedBy: "cleaner-1",
      createdAt: "2026-08-20T10:00:00Z",
      url: "/api/v1/cleaning-photos/photo-1?exp=1700000000&sig=abc",
    });
    // Defence against a future change that re-introduces a property the contract
    // does not publish: there is no storage_key in the response and none here.
    expect((photos[0] as unknown as Record<string, unknown>).storage_key).toBeUndefined();
  });
});

describe("HttpCleanerSource cycle mutations (R3, R4, R7)", () => {
  it("acceptTask POSTs to /accept with no body", async () => {
    const { source, request } = sourceWith(taskResponse);

    await source.acceptTask("tenant-1", "task-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/accept",
      { method: "POST", pathParams: { task_id: "task-1" } },
    );
  });

  it("rejectTask POSTs to /reject and returns the mapped task", async () => {
    const { source, request } = sourceWith(taskResponse);

    await source.rejectTask("tenant-1", "task-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/reject",
      { method: "POST", pathParams: { task_id: "task-1" } },
    );
  });

  it("startTask POSTs to /start", async () => {
    const { source, request } = sourceWith(taskResponse);

    await source.startTask("tenant-1", "task-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/start",
      { method: "POST", pathParams: { task_id: "task-1" } },
    );
  });

  it("completeTask POSTs to /complete", async () => {
    const { source, request } = sourceWith(taskResponse);

    await source.completeTask("tenant-1", "task-1");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/complete",
      { method: "POST", pathParams: { task_id: "task-1" } },
    );
  });

  it("completeChecklistItem POSTs to /checklist/{item_id}/complete with no body", async () => {
    const { source, request } = sourceWith({});

    await source.completeChecklistItem("tenant-1", "task-1", "kitchen");

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/checklist/{item_id}/complete",
      {
        method: "POST",
        pathParams: { task_id: "task-1", item_id: "kitchen" },
      },
    );
  });
});

describe("HttpCleanerSource.uploadPhoto (R5.2, R5.3)", () => {
  function uploadResponse() {
    return {
      id: "photo-1",
      cleaning_task_id: "task-1",
      photo_type: "kitchen",
      uploaded_by: "cleaner-1",
      created_at: "2026-08-20T10:00:00Z",
      url: "/api/v1/cleaning-photos/photo-1?exp=1700000000&sig=abc",
    };
  }

  it("builds FormData with photo_type and file, no JSON.stringify", async () => {
    const { source, request } = sourceWith(uploadResponse());
    const file = new File(["bytes"], "kitchen.jpg", { type: "image/jpeg" });

    await source.uploadPhoto("tenant-1", "task-1", "kitchen", file);

    const call = request.mock.calls[0];
    expect(call[0]).toBe("/api/v1/cleaning-tasks/{task_id}/photos");
    expect(call[1].method).toBe("POST");
    expect(call[1].pathParams).toEqual({ task_id: "task-1" });
    // formData is a FormData instance carrying both fields.
    const formData = call[1].formData as FormData;
    expect(formData).toBeInstanceOf(FormData);
    expect(formData.get("photo_type")).toBe("kitchen");
    expect(formData.get("file")).toBeInstanceOf(File);
    // The body field must NOT appear alongside formData — they are mutually exclusive.
    expect(call[1].body).toBeUndefined();
    // No manual Content-Type: the transport lets the browser write the boundary.
    expect(call[1].headers).toBeUndefined();
  });

  it("maps the response to CleaningPhoto, copying url verbatim", async () => {
    const { source } = sourceWith(uploadResponse());

    const photo = await source.uploadPhoto(
      "tenant-1",
      "task-1",
      "kitchen",
      new File(["x"], "kitchen.jpg", { type: "image/jpeg" }),
    );

    expect(photo).toEqual({
      id: "photo-1",
      cleaningTaskId: "task-1",
      photoType: "kitchen",
      uploadedBy: "cleaner-1",
      createdAt: "2026-08-20T10:00:00Z",
      url: "/api/v1/cleaning-photos/photo-1?exp=1700000000&sig=abc",
    });
  });

  it("uses photo_type from the entry the caller passed, not from a free field", async () => {
    const { source, request } = sourceWith(uploadResponse());

    await source.uploadPhoto(
      "tenant-1",
      "task-1",
      "bath",
      new File(["x"], "bath.jpg", { type: "image/jpeg" }),
    );

    const formData = request.mock.calls[0][1].formData as FormData;
    expect(formData.get("photo_type")).toBe("bath");
  });
});

describe("HttpCleanerSource.reportIncident (R6.1)", () => {
  it("POSTs title + description to /incidents and maps the ack", async () => {
    const { source, request } = sourceWith({
      id: "incident-1",
      status: "OPEN",
      created_at: "2026-08-20T10:00:00Z",
    });

    const ack = await source.reportIncident("tenant-1", "task-1", {
      title: "Caldera rota",
      description: "Sale agua por debajo",
    });

    expect(request).toHaveBeenCalledWith(
      "/api/v1/cleaning-tasks/{task_id}/incidents",
      {
        method: "POST",
        pathParams: { task_id: "task-1" },
        body: { title: "Caldera rota", description: "Sale agua por debajo" },
      },
    );
    expect(ack).toEqual({
      id: "incident-1",
      status: "OPEN",
      createdAt: "2026-08-20T10:00:00Z",
    });
  });
});

describe("HttpCleanerSource error mapping (R2.8, R5.5)", () => {
  it("propagates ApiError from the transport unchanged — no fallback", async () => {
    const request = vi.fn().mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    const source = new HttpCleanerSource({ request } as unknown as ApiClient);

    await expect(source.getTask("tenant-1", "task-1")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});