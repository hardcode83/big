import { describe, expect, it, vi } from "vitest";

import { ApiError, type ApiClient } from "@/lib/api";

import { HttpCleaningSource } from "./http-cleaning-source";

function sourceWith(response: unknown): {
  source: HttpCleaningSource;
  request: ReturnType<typeof vi.fn>;
} {
  const request = vi.fn().mockResolvedValue(response);
  return {
    source: new HttpCleaningSource({ request } as unknown as ApiClient),
    request,
  };
}

const taskResponse = {
  id: "task-1",
  property_id: "property-1",
  assigned_cleaner_id: "cleaner-1",
  status: "ASSIGNED",
  scheduled_start: "2026-08-20T09:00:00Z",
  scheduled_end: "2026-08-20T11:00:00Z",
  created_at: "2026-08-19T18:00:00Z",
  updated_at: "2026-08-19T18:05:00Z",
  accepted_at: null,
  completed_at: null,
  started_at: null,
  reservation_id: "reservation-1",
  checklist_template_id: "template-1",
  validated_at: null,
  validated_by_user_id: null,
  validation_status: "PENDING",
};

const mappedTask = {
  id: "task-1",
  propertyId: "property-1",
  assignedCleanerId: "cleaner-1",
  status: "ASSIGNED",
  scheduledStart: "2026-08-20T09:00:00Z",
  scheduledEnd: "2026-08-20T11:00:00Z",
  createdAt: "2026-08-19T18:00:00Z",
};

function taskPage(data: unknown[]) {
  return { data, total: data.length, page: 1, per_page: 20, total_pages: 1 };
}

describe("HttpCleaningSource.listTasks (R1.1, R1.5, R3.1–R3.3)", () => {
  it("sends page and per_page and no filter keys when none is chosen", async () => {
    const { source, request } = sourceWith(taskPage([taskResponse]));

    await expect(source.listTasks("tenant-1", {}, 3)).resolves.toEqual({
      data: [mappedTask],
      total: 1,
      page: 1,
      per_page: 20,
      total_pages: 1,
    });
    expect(request).toHaveBeenCalledWith("/api/v1/cleaning-tasks", {
      query: { page: 3, per_page: 20 },
    });
    // `toHaveBeenCalledWith` ignores keys whose value is `undefined`, so it would
    // pass on `{ property_id: undefined }` too. The key set is the real assertion.
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
    ]);
  });

  it("sends only the property filter when only the property is chosen", async () => {
    const { source, request } = sourceWith(taskPage([]));

    await source.listTasks("tenant-1", { propertyId: "property-7" }, 1);

    expect(request).toHaveBeenCalledWith("/api/v1/cleaning-tasks", {
      query: { page: 1, per_page: 20, property_id: "property-7" },
    });
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
      "property_id",
    ]);
  });

  it("combines both filters in the same request, so nothing is filtered client-side", async () => {
    const { source, request } = sourceWith(taskPage([]));

    await source.listTasks(
      "tenant-1",
      { propertyId: "property-7", status: "CREATED" },
      2,
    );

    expect(request).toHaveBeenCalledWith("/api/v1/cleaning-tasks", {
      query: {
        page: 2,
        per_page: 20,
        property_id: "property-7",
        status: "CREATED",
      },
    });
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
      "property_id",
      "status",
    ]);
  });

  it("preserves the backend's order and page envelope untouched", async () => {
    const { source } = sourceWith({
      data: [
        { ...taskResponse, id: "newer" },
        { ...taskResponse, id: "older" },
      ],
      total: 42,
      page: 2,
      per_page: 20,
      total_pages: 3,
    });

    const page = await source.listTasks("tenant-1", {}, 2);

    expect(page.data.map((task) => task.id)).toEqual(["newer", "older"]);
    expect(page).toMatchObject({ total: 42, page: 2, total_pages: 3 });
  });

  it("maps a task with no cleaner and no schedule to explicit nulls (R2.3)", async () => {
    const { source } = sourceWith(
      taskPage([
        {
          ...taskResponse,
          assigned_cleaner_id: null,
          scheduled_start: null,
          scheduled_end: null,
        },
      ]),
    );

    const page = await source.listTasks("tenant-1", {}, 1);

    expect(page.data[0]).toMatchObject({
      assignedCleanerId: null,
      scheduledStart: null,
      scheduledEnd: null,
    });
  });
});

describe("HttpCleaningSource.listCleaners (R2.2, design D4)", () => {
  it("asks for role=CLEANER with no status filter, so inactive cleaners still resolve", async () => {
    const { source, request } = sourceWith({
      data: [
        {
          id: "cleaner-1",
          name: "Marta Ruiz",
          email: "marta@example.com",
          role: "CLEANER",
          status: "ACTIVE",
          phone: null,
          preferred_language: "es",
          last_login_at: null,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
        {
          id: "cleaner-2",
          name: "Ana Pérez",
          email: "ana@example.com",
          role: "CLEANER",
          status: "INACTIVE",
          phone: null,
          preferred_language: "es",
          last_login_at: null,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
      total: 2,
      page: 1,
      per_page: 100,
      total_pages: 1,
    });

    await expect(source.listCleaners("tenant-1")).resolves.toEqual([
      { id: "cleaner-1", name: "Marta Ruiz", isActive: true },
      { id: "cleaner-2", name: "Ana Pérez", isActive: false },
    ]);
    expect(request).toHaveBeenCalledWith("/api/v1/users", {
      query: { page: 1, per_page: 100, role: "CLEANER" },
    });
    // Not `not.toHaveProperty("status")`: a `status: undefined` key would satisfy
    // that. The exact key set is what proves D4's "no status filter".
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
      "role",
    ]);
  });

  it.each(["SUSPENDED", "INACTIVE"] as const)(
    "treats %s as not active, so it is never offered as a candidate",
    async (status) => {
      const { source } = sourceWith({
        data: [
          {
            id: "cleaner-3",
            name: "Lucía Gil",
            email: "lucia@example.com",
            role: "CLEANER",
            status,
            phone: null,
            preferred_language: "es",
            last_login_at: null,
            created_at: "2026-08-01T00:00:00Z",
            updated_at: "2026-08-01T00:00:00Z",
          },
        ],
        total: 1,
        page: 1,
        per_page: 100,
        total_pages: 1,
      });

      const cleaners = await source.listCleaners("tenant-1");

      expect(cleaners[0]).toEqual({
        id: "cleaner-3",
        name: "Lucía Gil",
        isActive: false,
      });
    },
  );
});

describe("HttpCleaningSource.listProperties (R2.1)", () => {
  it("asks for one page of 100 and maps internal_code plus name", async () => {
    const { source, request } = sourceWith({
      data: [
        {
          id: "property-1",
          name: "Redes 11",
          internal_code: "REDES11",
          current_operational_state: "VACANT_READY",
          status: "ACTIVE",
          country: "ES",
          bedrooms: 2,
          bathrooms: 1,
          max_guests: 4,
          timezone: "Europe/Madrid",
          default_check_in_time: "16:00:00",
          default_check_out_time: "11:00:00",
          has_wifi_password: true,
          access_notes: null,
          address_line1: null,
          address_line2: null,
          city: null,
          cleaning_notes: null,
          emergency_notes: null,
          pms_external_id: null,
          pms_provider: null,
          postal_code: null,
          province: null,
          created_at: "2026-08-01T00:00:00Z",
          updated_at: "2026-08-01T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      per_page: 100,
      total_pages: 1,
    });

    await expect(source.listProperties("tenant-1")).resolves.toEqual([
      { id: "property-1", name: "Redes 11", internalCode: "REDES11" },
    ]);
    expect(request).toHaveBeenCalledWith("/api/v1/properties", {
      query: { page: 1, per_page: 100 },
    });
    expect(Object.keys(request.mock.calls[0][1].query).sort()).toEqual([
      "page",
      "per_page",
    ]);
  });
});

describe("HttpCleaningSource.assignTask (R4.6)", () => {
  it("PATCHes the task with assigned_cleaner_id as the only body field", async () => {
    const { source, request } = sourceWith({
      ...taskResponse,
      assigned_cleaner_id: "cleaner-9",
    });

    await expect(
      source.assignTask("tenant-1", "task-1", "cleaner-9"),
    ).resolves.toMatchObject({ assignedCleanerId: "cleaner-9" });

    expect(request).toHaveBeenCalledWith("/api/v1/cleaning-tasks/{task_id}", {
      method: "PATCH",
      pathParams: { task_id: "task-1" },
      body: { assigned_cleaner_id: "cleaner-9" },
    });
    const [, options] = request.mock.calls[0];
    expect(Object.keys(options.body)).toEqual(["assigned_cleaner_id"]);
  });

  it.each([403, 404, 409, 422, 500] as const)(
    "propagates an ApiError %s untouched, without wrapping or adapter retry",
    async (status) => {
      const error = new ApiError({
        code: "CODE",
        message: `API error ${status}`,
        status,
      });
      const request = vi.fn().mockRejectedValue(error);
      const source = new HttpCleaningSource({ request } as unknown as ApiClient);

      await expect(
        source.assignTask("tenant-1", "task-1", "cleaner-9"),
      ).rejects.toBe(error);
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
});
