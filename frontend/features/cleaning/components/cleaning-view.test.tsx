import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor, within } from "@/test/render";

import type {
  CleanerSummary,
  CleaningDataSource,
  CleaningTaskListItem,
  PaginatedResponse,
  PropertySummary,
} from "../data";
import { useCleaningFiltersStore } from "../state/use-cleaning-filters-store";
import { CleaningView } from "./cleaning-view";

const listTasks = vi.hoisted(() => vi.fn());
const listCleaners = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const assignTask = vi.hoisted(() => vi.fn());
const cancelTask = vi.hoisted(() => vi.fn());
const createTask = vi.hoisted(() => vi.fn());
const validateTask = vi.hoisted(() => vi.fn());

const role = vi.hoisted(() => ({ current: "PROPERTY_MANAGER" }));
const tenantId = vi.hoisted(() => ({ current: "tenant-1" }));
// Both paths: the hooks read `useAuth` from the barrel, while `lib/auth/permissions`
// imports it straight from `auth-provider` (it cannot use the barrel — the barrel
// re-exports it). Mocking only one leaves the other throwing. The factory body is
// inlined because `vi.mock` is hoisted above any plain top-level const.
vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  useAuth: () => ({ user: { tenant_id: tenantId.current, role: role.current } }),
}));
vi.mock("@/lib/auth/auth-provider", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/auth-provider")>()),
  useAuth: () => ({ user: { tenant_id: tenantId.current, role: role.current } }),
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getCleaningDataSource: (): CleaningDataSource => ({
    listTasks,
    listCleaners,
    listProperties,
    assignTask,
    cancelTask,
    createTask,
    validateTask,
  }),
}));

const PROPERTY_UUID = "8f14e45f-ceea-467a-9b7c-9d7c1a2b3c4d";
const CLEANER_UUID = "c9f0f895-fb98-4b41-a54b-2e1a7c0d9e8f";

const task: CleaningTaskListItem = {
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
  // Assignable by default, so every pre-existing test keeps describing the ordinary row.
  assignmentBlockedBy: null,
};

const cleaners: CleanerSummary[] = [
  { id: CLEANER_UUID, name: "Marta Ruiz", isActive: true },
];
const properties: PropertySummary[] = [
  {
    id: PROPERTY_UUID,
    name: "Redes 11",
    internalCode: "REDES11",
    currentOperationalState: "AWAITING_CLEANING",
  },
];

function page(
  data: CleaningTaskListItem[],
  envelope: Partial<PaginatedResponse<CleaningTaskListItem>> = {},
): PaginatedResponse<CleaningTaskListItem> {
  return {
    data,
    total: data.length,
    page: 1,
    per_page: 20,
    total_pages: data.length === 0 ? 0 : 1,
    ...envelope,
  };
}

/**
 * What a row *states*, with the assignment control's candidate list removed. R4.4 is
 * about the claim the row makes, not about which names the dropdown offers.
 */
function statedText(row: HTMLElement): string {
  const copy = row.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("select").forEach((node) => node.remove());
  return copy.textContent ?? "";
}

function renderView(locale: "es" | "en" = "es") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale={locale}>{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<CleaningView />, { wrapper: Wrapper });
}

beforeEach(() => {
  role.current = "PROPERTY_MANAGER";
  tenantId.current = "tenant-1";
  useCleaningFiltersStore.getState().reset();
  listTasks.mockReset().mockResolvedValue(page([task]));
  listCleaners.mockReset().mockResolvedValue(cleaners);
  listProperties.mockReset().mockResolvedValue(properties);
  assignTask.mockReset();
  createTask.mockReset();
  validateTask.mockReset();
  cancelTask.mockReset();
});

describe("CleaningView — the real list (R1.1)", () => {
  it("renders the page the source returned, and not the placeholder", async () => {
    renderView();

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /REDES11 · Redes 11/ }),
      ).toBeInTheDocument(),
    );
    const row = screen.getByRole("listitem");
    expect(statedText(row)).toContain("Marta Ruiz");
    expect(within(row).getByText("Asignada")).toBeInTheDocument();
    expect(screen.queryByText("En preparación")).not.toBeInTheDocument();
  });

  it("renders the tasks in the order the backend returned them", async () => {
    listTasks.mockResolvedValue(
      page([
        { ...task, id: "newer" },
        { ...task, id: "older", status: "COMPLETED" },
      ]),
    );
    renderView();

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    const items = screen.getAllByRole("listitem");
    expect(items[0].textContent).toContain("Asignada");
    expect(items[1].textContent).toContain("Completada");
  });
});

describe("CleaningView — the three states of the task query (R1.2, R1.3, R1.4)", () => {
  it("shows the accessible loading state while the request is in flight", () => {
    listTasks.mockReturnValue(new Promise(() => {}));
    renderView();

    const status = screen.getByRole("status", { busy: true });
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("shows an alert with a retry that re-runs the query", async () => {
    listTasks.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    renderView();

    await waitFor(() =>
      expect(
        screen.getByText("No se pudieron cargar las limpiezas"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();

    listTasks.mockResolvedValue(page([task]));
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /REDES11 · Redes 11/ })).toBeInTheDocument(),
    );
  });

  it("never shows the backend's technical message", async () => {
    listTasks.mockRejectedValue(
      new ApiError({
        code: "FORBIDDEN",
        message: "psycopg.OperationalError: connection refused",
        status: 403,
      }),
    );
    const { container } = renderView();

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(container.textContent).not.toContain("psycopg");
  });

  it("shows an empty state distinguishable from error and loading, with filters active", async () => {
    listTasks.mockResolvedValue(page([]));
    renderView();
    fireEvent.change(screen.getByRole("combobox", { name: "Estado" }), {
      target: { value: "FAILED" },
    });

    await waitFor(() =>
      expect(screen.getByText("Sin tareas de limpieza")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { busy: true })).not.toBeInTheDocument();
  });
});

describe("CleaningView — a catalog failure never takes the list down (R2.4, design D5)", () => {
  it("renders the list with a degraded identity when both catalogs fail", async () => {
    listCleaners.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    listProperties.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    renderView();

    await waitFor(() =>
      expect(screen.getAllByText("Identidad no disponible")).toHaveLength(2),
    );
    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Asignada")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByText("No se pudieron cargar las limpiezas"),
    ).not.toBeInTheDocument();
  });
});

describe("CleaningView — filters travel to the request (R3.1, R3.2, R3.3)", () => {
  it("sends the chosen status to the source and never filters in the client", async () => {
    renderView();
    await waitFor(() => expect(listTasks).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("combobox", { name: "Estado" }), {
      target: { value: "COMPLETED" },
    });

    await waitFor(() =>
      expect(listTasks).toHaveBeenCalledWith(
        "tenant-1",
        { status: "COMPLETED" },
        1,
      ),
    );
  });

  it("combines both filters in the same request", async () => {
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: "REDES11 · Redes 11" }),
      ).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Vivienda" }), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Estado" }), {
      target: { value: "CREATED" },
    });

    await waitFor(() =>
      expect(listTasks).toHaveBeenCalledWith(
        "tenant-1",
        { propertyId: PROPERTY_UUID, status: "CREATED" },
        1,
      ),
    );
  });
});

describe("CleaningView — pagination (R1.5)", () => {
  it("reflects the envelope and asks the source for the next page", async () => {
    listTasks.mockResolvedValue(
      page([task], { total: 45, page: 1, total_pages: 3 }),
    );
    renderView();

    await waitFor(() =>
      expect(screen.getByText(/Página 1 de 3/)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));

    await waitFor(() =>
      expect(listTasks).toHaveBeenCalledWith("tenant-1", {}, 2),
    );
  });

  it("fetches each catalog once across a page change (R2.5)", async () => {
    listTasks.mockResolvedValue(
      page([task], { total: 45, page: 1, total_pages: 3 }),
    );
    renderView();

    await waitFor(() => expect(screen.getByText(/Página 1 de 3/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));

    expect(listCleaners).toHaveBeenCalledTimes(1);
    expect(listProperties).toHaveBeenCalledTimes(1);
  });
});

describe("CleaningView — the single live region (design D11)", () => {
  it("is present from the first render, before any assignment happened", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /REDES11 · Redes 11/ })).toBeInTheDocument(),
    );

    const regions = screen
      .getAllByRole("status")
      .filter((node) => node.getAttribute("aria-busy") === null);
    expect(regions).toHaveLength(1);
    expect(regions[0]).toHaveAttribute("aria-live", "polite");
  });
});

describe("CleaningView — every status, in both locales (R1.6, R5.1)", () => {
  it.each([
    ["CREATED", "Creada"],
    ["ASSIGNED", "Asignada"],
    ["ACCEPTED", "Aceptada"],
    ["REJECTED", "Rechazada"],
    ["IN_PROGRESS", "En curso"],
    ["PENDING_REVIEW", "Pendiente de revisión"],
    ["COMPLETED", "Completada"],
    ["FAILED", "Fallida"],
    ["CANCELLED", "Cancelada"],
  ] as const)("renders %s with its translated label", async (status, label) => {
    listTasks.mockResolvedValue(page([{ ...task, status }]));
    const { container } = renderView();

    await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument());
    expect(container.textContent).not.toContain(status);
  });

  it("renders the whole view in English", async () => {
    renderView("en");
    await waitFor(() =>
      expect(screen.getByText("Assigned")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("combobox", { name: "Property" }),
    ).toBeInTheDocument();
  });
});

describe("CleaningView — assigning from the list (R4.1, R4.3, R4.4, R4.5, R5.4)", () => {
  const control = () =>
    screen.getByRole("combobox", { name: "Asignar limpiadora" });

  async function renderWithControl() {
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() => expect(control()).toBeInTheDocument());
  }

  it("shows the control to a PROPERTY_MANAGER and no read-only name in its place (R4.3)", async () => {
    await renderWithControl();
    const row = screen.getByRole("listitem");
    expect(within(row).getByRole("combobox", { name: "Asignar limpiadora" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Asignar" })).toBeInTheDocument();
  });

  it("hides the control from a TENANT_OWNER and keeps the name as text (R4.3)", async () => {
    role.current = "TENANT_OWNER";
    renderView();

    await waitFor(() =>
      expect(screen.getByRole("listitem")).toBeInTheDocument(),
    );
    const row = screen.getByRole("listitem");
    expect(within(row).getByText("Marta Ruiz")).toBeInTheDocument();
    expect(
      within(row).queryByRole("combobox", { name: "Asignar limpiadora" }),
    ).not.toBeInTheDocument();
    expect(
      within(row).queryByRole("button", { name: "Asignar" }),
    ).not.toBeInTheDocument();
  });

  it("sends only the task and the cleaner, and announces the success (R4.1, R4.6, R5.4)", async () => {
    await renderWithControl();
    assignTask.mockResolvedValue({ ...task, assignedCleanerId: "cleaner-2" });
    listTasks.mockResolvedValue(
      page([{ ...task, assignedCleanerId: "cleaner-2" }]),
    );

    fireEvent.change(control(), { target: { value: "cleaner-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

    await waitFor(() =>
      expect(
        screen.getByText("Tarea asignada a Lucía Gil."),
      ).toBeInTheDocument(),
    );
    expect(assignTask).toHaveBeenCalledExactlyOnceWith(
      "tenant-1",
      "task-1",
      "cleaner-2",
    );
    // The refreshed list is what shows the new assignment, not an optimistic write.
    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));
  });

  it("does not send anything when the select merely changes (design D8)", async () => {
    await renderWithControl();
    fireEvent.change(control(), { target: { value: "cleaner-2" } });
    expect(assignTask).not.toHaveBeenCalled();
  });

  it("announces the success inside the polite region, not as an alert (design D11)", async () => {
    await renderWithControl();
    assignTask.mockResolvedValue({ ...task, assignedCleanerId: "cleaner-2" });

    fireEvent.change(control(), { target: { value: "cleaner-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

    await waitFor(() =>
      expect(screen.getByText("Tarea asignada a Lucía Gil.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const region = screen
      .getAllByRole("status")
      .find((node) => node.getAttribute("aria-live") === "polite");
    expect(region?.textContent).toBe("Tarea asignada a Lucía Gil.");
  });

  it.each([
    [403, "No tienes permiso para asignar limpiezas."],
    [404, "Esa tarea de limpieza ya no existe."],
    [409, "Esa tarea ya no admite un cambio de asignación."],
    [422, "Esa persona ya no es una limpiadora activa de este tenant."],
    [500, "No se pudo asignar la limpieza. Vuelve a intentarlo."],
  ] as const)(
    "announces the translated message for %s, refreshes, and never shows the rejected assignment (R4.4, R4.5)",
    async (status, message) => {
      await renderWithControl();
      assignTask.mockRejectedValue(
        new ApiError({ code: "CODE", message: "backend detail", status }),
      );

      fireEvent.change(control(), { target: { value: "cleaner-2" } });
      fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

      await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument());
      // The failure is an alert inside the same single live region (design D11).
      expect(screen.getByRole("alert").textContent).toBe(message);
      // R4.5: the list is refreshed even though the write failed.
      await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));
      // R4.4: the row keeps stating what the backend has and never the rejected
      // pick. The pick survives in the dropdown so the manager can retry, which is
      // why this looks at what the row states rather than at the whole subtree.
      const row = screen.getByRole("listitem");
      expect(statedText(row)).toContain("Marta Ruiz");
      expect(statedText(row)).not.toContain("Lucía Gil");
      // And never the backend's technical text (R5.1, design D10).
      expect(document.body.textContent).not.toContain("backend detail");
    },
  );

  it("drops a task that leaves the active filter once the list refreshes (design D9)", async () => {
    listTasks.mockResolvedValue(page([{ ...task, status: "CREATED" }]));
    await renderWithControl();
    fireEvent.change(screen.getByRole("combobox", { name: "Estado" }), {
      target: { value: "CREATED" },
    });
    await waitFor(() => expect(screen.getByRole("listitem")).toBeInTheDocument());

    // Assigning moves it CREATED → ASSIGNED, so the CREATED-filtered page loses it.
    assignTask.mockResolvedValue({ ...task, assignedCleanerId: "cleaner-2" });
    listTasks.mockResolvedValue(page([]));

    fireEvent.change(control(), { target: { value: "cleaner-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

    await waitFor(() =>
      expect(screen.getByText("Sin tareas de limpieza")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });
});

describe("CleaningView — filters do not outlive their session (security.md rule 1)", () => {
  it("drops a previous tenant's filter instead of re-sending it", async () => {
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /REDES11/ }),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Vivienda" }), {
      target: { value: PROPERTY_UUID },
    });
    await waitFor(() =>
      expect(listTasks).toHaveBeenCalledWith(
        "tenant-1",
        { propertyId: PROPERTY_UUID },
        1,
      ),
    );

    // A different identity takes over the same tab — the store is a module-level
    // singleton, so without the reset its `propertyId` would ride along.
    listTasks.mockClear();
    tenantId.current = "tenant-2";
    renderView();

    await waitFor(() => expect(listTasks).toHaveBeenCalled());
    for (const call of listTasks.mock.calls) {
      expect(call[1]).toEqual({});
      expect(JSON.stringify(call)).not.toContain(PROPERTY_UUID);
    }
    expect(useCleaningFiltersStore.getState()).toMatchObject({
      propertyId: undefined,
      status: undefined,
      page: 1,
    });
  });
});

describe("CleaningView — one assignment at a time (R4.4, R4.5)", () => {
  it("blocks every other row while one assignment is in flight, so no rejection is lost", async () => {
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    listTasks.mockResolvedValue(
      page([task, { ...task, id: "task-2", status: "CREATED" }]),
    );
    // Never settles: the first assignment stays in flight for the whole test.
    assignTask.mockReturnValue(new Promise(() => {}));
    renderView();

    await waitFor(() =>
      expect(
        screen.getAllByRole("combobox", { name: "Asignar limpiadora" }),
      ).toHaveLength(2),
    );
    const [first, second] = screen.getAllByRole("combobox", {
      name: "Asignar limpiadora",
    });

    // Arm BOTH rows first. Without this the second row's button would be disabled
    // merely because nothing is picked, and the test would pass even with the
    // concurrency guard removed — it would prove nothing.
    fireEvent.change(second, { target: { value: "cleaner-2" } });
    expect(screen.getAllByRole("button", { name: "Asignar" })[1]).toBeEnabled();

    fireEvent.change(first, { target: { value: "cleaner-2" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Asignar" })[0]);

    // The view owns a single mutation: a second `mutate` would detach the first and
    // swallow its rejection, which R4.4/R4.5 require to be announced. So an armed
    // second row still cannot be confirmed until the first settles.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Asignar" })[0]).toBeDisabled(),
    );
    expect(assignTask).toHaveBeenCalledTimes(1);

    // But its select stays enabled and keeps focus: disabling a focused element
    // drops focus to <body> and strands a keyboard user mid-pick (R5.3).
    expect(second).toBeEnabled();
    second.focus();
    expect(second).toHaveFocus();
  });

  it("says which row is sending, and does not claim the others are", async () => {
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    listTasks.mockResolvedValue(
      page([task, { ...task, id: "task-2", status: "CREATED" }]),
    );
    assignTask.mockReturnValue(new Promise(() => {}));
    renderView();

    await waitFor(() =>
      expect(
        screen.getAllByRole("combobox", { name: "Asignar limpiadora" }),
      ).toHaveLength(2),
    );
    fireEvent.change(
      screen.getAllByRole("combobox", { name: "Asignar limpiadora" })[0],
      { target: { value: "cleaner-2" } },
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Asignar" })[0]);

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: "Asignando…" }),
      ).toHaveLength(1),
    );
  });
});

describe("CleaningView — the pre-flight, and the race it does not pretend to win (R3.1, R3.3)", () => {
  const OTHER_PROPERTY = "2b7e1516-28ae-4d2a-a6ab-f7158809cf4f";

  it("shows a blocked row and an assignable one in the same list", async () => {
    listTasks.mockResolvedValue(
      page([
        { ...task, assignmentBlockedBy: null },
        {
          ...task,
          id: "task-2",
          propertyId: OTHER_PROPERTY,
          assignmentBlockedBy: "PROPERTY_STATE",
        },
      ]),
    );
    listProperties.mockResolvedValue([
      ...properties,
      { id: OTHER_PROPERTY, name: "Pajaritos 8", internalCode: "PAJARITOS8" },
    ]);
    renderView();

    await waitFor(() =>
      expect(screen.getAllByRole("listitem")).toHaveLength(2),
    );
    const [assignable, blocked] = screen.getAllByRole("listitem");
    expect(
      within(blocked).getByText(
        "No se puede asignar todavía: la vivienda no está pendiente de limpieza.",
      ),
    ).toBeInTheDocument();
    expect(within(blocked).getByRole("button", { name: "Asignar" })).toBeDisabled();
    expect(
      within(assignable).queryByText(/No se puede asignar/),
    ).not.toBeInTheDocument();
  });

  it("announces the property message for a real 409 the row had offered (R3.3)", async () => {
    // The heart of R3.3. The row said `null` — assignable — because that is what the page
    // read saw; between the read and the click the flat moved, and the backend refused. The
    // guard was a courtesy, the refusal is the authority, and the message the manager sees
    // must now name the **property**, which before this change it never did: both 409s
    // shared one code and the screen blamed the task.
    listTasks.mockResolvedValue(page([{ ...task, assignmentBlockedBy: null }]));
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      ).toBeInTheDocument(),
    );
    assignTask.mockRejectedValue(
      new ApiError({
        code: "PROPERTY_STATE_CONFLICT",
        message: "No policy entry for source state and trigger",
        status: 409,
      }),
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Asignar limpiadora" }), {
      target: { value: "cleaner-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

    await waitFor(() =>
      expect(
        screen.getByText("La vivienda todavía no está pendiente de limpieza."),
      ).toBeInTheDocument(),
    );
    // Still the single live region of design D11, and still an alert for a failure.
    expect(screen.getByRole("alert").textContent).toBe(
      "La vivienda todavía no está pendiente de limpieza.",
    );
    // And emphatically NOT the task sentence, which is the bug this change exists to fix.
    expect(document.body.textContent).not.toContain(
      "Esa tarea ya no admite un cambio de asignación.",
    );
    // Never the backend's technical English (R2.3, R5.1).
    expect(document.body.textContent).not.toContain("No policy entry");
  });

  it("still blames the task when the task is what refused", async () => {
    listTasks.mockResolvedValue(page([{ ...task, assignmentBlockedBy: null }]));
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      ).toBeInTheDocument(),
    );
    assignTask.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "detail", status: 409 }),
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Asignar limpiadora" }), {
      target: { value: "cleaner-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

    await waitFor(() =>
      expect(
        screen.getByText("Esa tarea ya no admite un cambio de asignación."),
      ).toBeInTheDocument(),
    );
    expect(document.body.textContent).not.toContain(
      "La vivienda todavía no está pendiente de limpieza.",
    );
  });
});

describe("CleaningView — the create control (R1.1, R5.1)", () => {
  it("offers the create control to a PROPERTY_MANAGER", async () => {
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Nueva limpieza" }),
      ).toBeInTheDocument(),
    );
  });

  it("hides the create control from a role without MANAGE_CLEANING_TASKS", async () => {
    role.current = "TENANT_OWNER";
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("listitem")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Nueva limpieza" }),
    ).not.toBeInTheDocument();
  });
});

describe("CleaningView — creating a task (R1.1, R1.3, R1.4, R1.5)", () => {
  async function openCreatePanel() {
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Nueva limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByLabelText("Vivienda de la nueva tarea"),
      ).toBeInTheDocument(),
    );
  }

  it("sends the create input, invalidates the listing, announces success, and closes the panel", async () => {
    await openCreatePanel();
    createTask.mockResolvedValue({
      id: "task-2",
      propertyId: PROPERTY_UUID,
      assignedCleanerId: null,
      status: "CREATED",
      scheduledStart: null,
      scheduledEnd: null,
      createdAt: "2026-09-06T10:00:00Z",
      completedAt: null,
      validationStatus: "PENDING",
      validatedAt: null,
    });
    listTasks.mockResolvedValue(page([task, { ...task, id: "task-2" }]));

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() =>
      expect(
        screen.getByText("Tarea de limpieza creada."),
      ).toBeInTheDocument(),
    );
    expect(createTask).toHaveBeenCalledExactlyOnceWith("tenant-1", {
      propertyId: PROPERTY_UUID,
    });
    // R1.3: the listing key is invalidated so the new row appears without a
    // manual reload — the same refetch mechanism assignment already uses.
    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));
    // The panel closes on success — its field is no longer in the document.
    expect(
      screen.queryByLabelText("Vivienda de la nueva tarea"),
    ).not.toBeInTheDocument();
    // Still the single live region, and success is not an alert.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [403, "No tienes permiso para crear limpiezas."],
    [404, "Esa vivienda ya no existe, o no tiene una plantilla de checklist activa."],
    [
      409,
      "Esa vivienda admite más de una plantilla de checklist activa; no se puede crear la tarea.",
    ],
    [422, "Revisa los datos introducidos."],
    [500, "No se pudo crear la limpieza. Vuelve a intentarlo."],
  ] as const)(
    "announces the translated message for %s and keeps the panel open (R1.4)",
    async (status, message) => {
      await openCreatePanel();
      createTask.mockRejectedValue(
        new ApiError({ code: "CODE", message: "backend detail", status }),
      );

      fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
        target: { value: PROPERTY_UUID },
      });
      fireEvent.click(screen.getByRole("button", { name: "Crear" }));

      await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument());
      expect(screen.getByRole("alert").textContent).toBe(message);
      // The panel stays open so the manager can see the failure and retry.
      expect(
        screen.getByLabelText("Vivienda de la nueva tarea"),
      ).toBeInTheDocument();
      // Never the backend's technical text (R5.1, design D10).
      expect(document.body.textContent).not.toContain("backend detail");
      // Still the single live region while the mutation is in its error state,
      // not just while it is pending (design D11).
      expect(
        screen
          .getAllByRole("status")
          .filter((node) => node.getAttribute("aria-busy") === null),
      ).toHaveLength(1);
    },
  );

  it("never opens a second live region while creating", async () => {
    await openCreatePanel();
    createTask.mockReturnValue(new Promise(() => {}));

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    // Both the submit button and the live region can legitimately say "Creando…"
    // at once, so this asserts on the region specifically, not on the text.
    await waitFor(() => {
      const region = screen
        .getAllByRole("status")
        .find((node) => node.getAttribute("aria-live") === "polite");
      expect(region?.textContent).toBe("Creando…");
    });
    const regions = screen
      .getAllByRole("status")
      .filter((node) => node.getAttribute("aria-busy") === null);
    expect(regions).toHaveLength(1);
  });
});

describe("CleaningView — precedence between create and assign (design D4)", () => {
  async function openCreatePanel() {
    fireEvent.click(await screen.findByRole("button", { name: "Nueva limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByLabelText("Vivienda de la nueva tarea"),
      ).toBeInTheDocument(),
    );
  }

  it("shows create's pending message over a settled assign success", async () => {
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      ).toBeInTheDocument(),
    );
    assignTask.mockResolvedValue({ ...task, assignedCleanerId: "cleaner-2" });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      { target: { value: "cleaner-2" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));
    await waitFor(() =>
      expect(
        screen.getByText("Tarea asignada a Lucía Gil."),
      ).toBeInTheDocument(),
    );

    // Now start a creation that never settles: it must outrank the already
    // -settled assign success, per the "isPending wins outright" rule.
    createTask.mockReturnValue(new Promise(() => {}));
    await openCreatePanel();
    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    // Both the submit button and the live region can legitimately say "Creando…"
    // at once, so this asserts on the region specifically, not on the text.
    await waitFor(() => {
      const region = screen
        .getAllByRole("status")
        .find((node) => node.getAttribute("aria-live") === "polite");
      expect(region?.textContent).toBe("Creando…");
    });
    expect(
      screen.queryByText("Tarea asignada a Lucía Gil."),
    ).not.toBeInTheDocument();
  });

  it("prefers the most recently submitted error between the two mutations", async () => {
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      ).toBeInTheDocument(),
    );

    // The assignment fails first...
    assignTask.mockRejectedValue(
      new ApiError({ code: "CODE", message: "assign failed", status: 403 }),
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      { target: { value: "cleaner-2" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));
    await waitFor(() =>
      expect(
        screen.getByText("No tienes permiso para asignar limpiezas."),
      ).toBeInTheDocument(),
    );

    // ...and creation fails afterwards: its error, submitted later, wins.
    createTask.mockRejectedValue(
      new ApiError({ code: "CODE", message: "create failed", status: 422 }),
    );
    await openCreatePanel();
    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() =>
      expect(
        screen.getByText("Revisa los datos introducidos."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText("No tienes permiso para asignar limpiezas."),
    ).not.toBeInTheDocument();
    // Still exactly one live region throughout.
    expect(
      screen
        .getAllByRole("status")
        .filter((node) => node.getAttribute("aria-busy") === null),
    ).toHaveLength(1);
  });

  it("prefers assign's error over create's when assign is submitted later, despite create being declared first in the sources array", async () => {
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      ).toBeInTheDocument(),
    );

    // Creation fails first...
    createTask.mockRejectedValue(
      new ApiError({ code: "CODE", message: "create failed", status: 422 }),
    );
    await openCreatePanel();
    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() =>
      expect(
        screen.getByText("Revisa los datos introducidos."),
      ).toBeInTheDocument(),
    );

    // ...and the assignment fails afterwards: its error, submitted later, wins —
    // this is the only case that falsifies "array position drives the pick"
    // (`create` is declared first in the fixed `[create, assign]` array) versus
    // "submittedAt drives the pick".
    assignTask.mockRejectedValue(
      new ApiError({ code: "CODE", message: "assign failed", status: 403 }),
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Asignar limpiadora" }),
      { target: { value: "cleaner-2" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Asignar" }));

    await waitFor(() =>
      expect(
        screen.getByText("No tienes permiso para asignar limpiezas."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText("Revisa los datos introducidos."),
    ).not.toBeInTheDocument();
    // Still exactly one live region throughout.
    expect(
      screen
        .getAllByRole("status")
        .filter((node) => node.getAttribute("aria-busy") === null),
    ).toHaveLength(1);
  });
});

describe("CleaningView — validating a completed task (R3.1, R3.2, R3.5)", () => {
  const completedTask: CleaningTaskListItem = {
    ...task,
    status: "COMPLETED",
    completedAt: "2026-08-20T12:00:00Z",
    validationStatus: "PENDING",
  };

  it("offers the control to a PROPERTY_MANAGER on a COMPLETED task", async () => {
    listTasks.mockResolvedValue(page([completedTask]));
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Validar" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "No pasa" })).toBeInTheDocument();
  });

  it("hides the control from a TENANT_OWNER, though the verdict field still shows", async () => {
    role.current = "TENANT_OWNER";
    listTasks.mockResolvedValue(page([completedTask]));
    renderView();
    await waitFor(() =>
      expect(screen.getByText("Pendiente de validación")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Validar" })).not.toBeInTheDocument();
  });

  it("sends the task id and verdict, invalidates the listing, and announces success", async () => {
    listTasks.mockResolvedValue(page([completedTask]));
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Validar" })).toBeInTheDocument(),
    );

    validateTask.mockResolvedValue({
      ...completedTask,
      validationStatus: "PASSED",
      validatedAt: "2026-08-20T13:00:00Z",
    });
    listTasks.mockResolvedValue(
      page([{ ...completedTask, validationStatus: "PASSED" }]),
    );

    fireEvent.click(screen.getByRole("button", { name: "Validar" }));

    await waitFor(() =>
      expect(
        screen.getByText("Limpieza validada como correcta."),
      ).toBeInTheDocument(),
    );
    expect(validateTask).toHaveBeenCalledExactlyOnceWith(
      "tenant-1",
      "task-1",
      "PASSED",
    );
    // R3.2: the listing key is invalidated so the fresh verdict appears.
    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("announces the FAILED-specific success copy", async () => {
    listTasks.mockResolvedValue(page([completedTask]));
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "No pasa" })).toBeInTheDocument(),
    );

    validateTask.mockResolvedValue({
      ...completedTask,
      validationStatus: "FAILED",
      validatedAt: "2026-08-20T13:00:00Z",
    });

    fireEvent.click(screen.getByRole("button", { name: "No pasa" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Limpieza marcada como no conforme; se ha notificado a la limpiadora asignada.",
        ),
      ).toBeInTheDocument(),
    );
    expect(validateTask).toHaveBeenCalledExactlyOnceWith(
      "tenant-1",
      "task-1",
      "FAILED",
    );
  });

  it.each([
    [403, "No tienes permiso para validar limpiezas."],
    [404, "Esa tarea de limpieza ya no existe."],
    [409, "Esa tarea ya no está completada; no se puede validar."],
    [500, "No se pudo validar la limpieza. Vuelve a intentarlo."],
  ] as const)(
    "announces the translated message for %s (R3.5)",
    async (status, message) => {
      listTasks.mockResolvedValue(page([completedTask]));
      renderView();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Validar" })).toBeInTheDocument(),
      );

      validateTask.mockRejectedValue(
        new ApiError({ code: "CODE", message: "backend detail", status }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Validar" }));

      await waitFor(() => expect(screen.getByText(message)).toBeInTheDocument());
      expect(screen.getByRole("alert").textContent).toBe(message);
      // R3.5: still invalidated even on failure.
      await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));
      expect(document.body.textContent).not.toContain("backend detail");
    },
  );

  it("blocks a second row's verdict while the first is still in flight", async () => {
    listTasks.mockResolvedValue(
      page([completedTask, { ...completedTask, id: "task-2" }]),
    );
    validateTask.mockReturnValue(new Promise(() => {}));
    renderView();

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Validar" })).toHaveLength(2),
    );
    const [first, second] = screen.getAllByRole("button", { name: "Validar" });
    fireEvent.click(first);

    await waitFor(() => expect(first).toBeDisabled());
    expect(second).toBeDisabled();
    expect(validateTask).toHaveBeenCalledTimes(1);
  });
});

describe("CleaningView — precedence including validate (design D4)", () => {
  const completedTask: CleaningTaskListItem = {
    ...task,
    status: "COMPLETED",
    completedAt: "2026-08-20T12:00:00Z",
    validationStatus: "PENDING",
  };

  it("shows validate's pending message over a settled assign success", async () => {
    listTasks.mockResolvedValue(page([completedTask]));
    listCleaners.mockResolvedValue([
      ...cleaners,
      { id: "cleaner-2", name: "Lucía Gil", isActive: true },
    ]);
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Validar" })).toBeInTheDocument(),
    );

    // Settle create's success first, then start a validate that never settles —
    // it must outrank the already-settled success, per the "isPending wins
    // outright" rule (mirrors the create-vs-assign test above).
    createTask.mockResolvedValue({
      id: "task-2",
      propertyId: PROPERTY_UUID,
      assignedCleanerId: null,
      status: "CREATED",
      scheduledStart: null,
      scheduledEnd: null,
      createdAt: "2026-09-06T10:00:00Z",
      completedAt: null,
      validationStatus: "PENDING",
      validatedAt: null,
    });
    fireEvent.click(screen.getByRole("button", { name: "Nueva limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByLabelText("Vivienda de la nueva tarea"),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));
    await waitFor(() =>
      expect(
        screen.getByText("Tarea de limpieza creada."),
      ).toBeInTheDocument(),
    );

    validateTask.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Validar" }));

    await waitFor(() => {
      const region = screen
        .getAllByRole("status")
        .find((node) => node.getAttribute("aria-live") === "polite");
      expect(region?.textContent).toBe("Enviando…");
    });
    expect(
      screen.queryByText("Tarea de limpieza creada."),
    ).not.toBeInTheDocument();
  });

  it("prefers validate's error over an earlier create error, by submittedAt", async () => {
    listTasks.mockResolvedValue(page([completedTask]));
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Validar" })).toBeInTheDocument(),
    );

    createTask.mockRejectedValue(
      new ApiError({ code: "CODE", message: "create failed", status: 422 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Nueva limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByLabelText("Vivienda de la nueva tarea"),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));
    await waitFor(() =>
      expect(
        screen.getByText("Revisa los datos introducidos."),
      ).toBeInTheDocument(),
    );

    validateTask.mockRejectedValue(
      new ApiError({ code: "CODE", message: "validate failed", status: 409 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Validar" }));

    await waitFor(() =>
      expect(
        screen.getByText("Esa tarea ya no está completada; no se puede validar."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByText("Revisa los datos introducidos."),
    ).not.toBeInTheDocument();
    expect(
      screen
        .getAllByRole("status")
        .filter((node) => node.getAttribute("aria-busy") === null),
    ).toHaveLength(1);
  });
});

describe("CleaningView — cancelling a live task (R4.1, R4.2, R4.3, R4.4)", () => {
  async function openCancelDialog() {
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toBeInTheDocument(),
    );
  }

  it("offers the control to a PROPERTY_MANAGER on a live task", async () => {
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument(),
    );
  });

  it("hides the control from a role without MANAGE_CLEANING_TASKS", async () => {
    role.current = "TENANT_OWNER";
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("listitem")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });

  it("hides the control once the task is terminal", async () => {
    listTasks.mockResolvedValue(page([{ ...task, status: "COMPLETED" }]));
    renderView();
    await waitFor(() =>
      expect(screen.getByRole("listitem")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });

  it("sends only the task id and the trimmed reason (R4.2)", async () => {
    await openCancelDialog();
    cancelTask.mockResolvedValue({ ...task, status: "CANCELLED" });
    listTasks.mockResolvedValue(page([{ ...task, status: "CANCELLED" }]));

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  la limpiadora no volvió  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar cancelación" }));

    await waitFor(() =>
      expect(cancelTask).toHaveBeenCalledExactlyOnceWith(
        "tenant-1",
        "task-1",
        "la limpiadora no volvió",
      ),
    );
  });

  it("invalidates the listing on success, closes the dialog, and announces success in the region (R4.3, design D4)", async () => {
    await openCancelDialog();
    cancelTask.mockResolvedValue({ ...task, status: "CANCELLED" });
    listTasks.mockResolvedValue(
      page([
        { ...task, status: "CANCELLED" },
        { ...task, id: "task-2", status: "CREATED" },
      ]),
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar cancelación" }));

    await waitFor(() =>
      expect(screen.getByText("Limpieza cancelada.")).toBeInTheDocument(),
    );
    // The dialog has closed — its form is no longer on screen.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    // R4.3: the listing is refreshed so both the cancelled task and its replacement show.
    await waitFor(() => expect(listTasks).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the dialog open on failure and paints the alert inside it, not in the region (design D4, R4.5)", async () => {
    await openCancelDialog();
    cancelTask.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "already terminal", status: 409 }),
    );

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar cancelación" }));

    await waitFor(() =>
      expect(
        screen.getByText("Esa tarea ya está cerrada; no se puede cancelar."),
      ).toBeInTheDocument(),
    );
    // The dialog is still on screen — closing only happens on success (design D4).
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    // And the single live region says nothing about it: the alert lives in the
    // dialog only, never duplicated into the region.
    const region = screen
      .getAllByRole("status")
      .find((node) => node.getAttribute("aria-live") === "polite");
    expect(region?.textContent).toBe("");
    expect(document.body.textContent).not.toContain("already terminal");
  });

  it("closes the dialog through its own close control without cancelling anything", async () => {
    await openCancelDialog();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar limpieza" }));
    await waitFor(() =>
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument(),
    );
    expect(cancelTask).not.toHaveBeenCalled();
  });

  it("shows cancel's pending message over a settled create success (design D4 precedence)", async () => {
    renderView();
    createTask.mockResolvedValue({
      id: "task-2",
      propertyId: PROPERTY_UUID,
      assignedCleanerId: null,
      status: "CREATED",
      scheduledStart: null,
      scheduledEnd: null,
      createdAt: "2026-09-06T10:00:00Z",
      completedAt: null,
      validationStatus: "PENDING",
      validatedAt: null,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Nueva limpieza" }));
    await waitFor(() =>
      expect(
        screen.getByLabelText("Vivienda de la nueva tarea"),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: PROPERTY_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));
    await waitFor(() =>
      expect(screen.getByText("Tarea de limpieza creada.")).toBeInTheDocument(),
    );

    cancelTask.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar cancelación" }));

    await waitFor(() => {
      const region = screen
        .getAllByRole("status")
        .find((node) => node.getAttribute("aria-live") === "polite");
      expect(region?.textContent).toBe("Cancelando…");
    });
    expect(
      screen.queryByText("Tarea de limpieza creada."),
    ).not.toBeInTheDocument();
  });

  it("blocks every other row's cancel button, and this row's own dismiss, while a cancellation is in flight (fix round, Finding 1, D4)", async () => {
    listTasks.mockResolvedValue(
      page([task, { ...task, id: "task-2", status: "CREATED" }]),
    );
    // Never settles: the cancellation stays in flight for the whole test.
    cancelTask.mockReturnValue(new Promise(() => {}));
    renderView();

    const openButtons = await screen.findAllByRole("button", { name: "Cancelar" });
    expect(openButtons).toHaveLength(2);
    fireEvent.click(openButtons[0]);
    await waitFor(() => expect(screen.getByRole("textbox")).toBeInTheDocument());

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar cancelación" }));
    await waitFor(() => expect(cancelTask).toHaveBeenCalledTimes(1));

    // While the sheet is open (modal), Radix already marks everything behind it
    // `aria-hidden`, so task-2's "Cancelar" button is unreachable via the accessible
    // tree — `getAllByRole` finds none, not even task-1's own (also behind the
    // overlay). That is not new; what Finding 1 requires is that this state cannot
    // be escaped while the request is in flight.
    expect(screen.queryAllByRole("button", { name: "Cancelar" })).toHaveLength(0);

    // The currently open dialog's own dismiss affordances (its close button here)
    // do nothing while the request is still in flight — without this, dismissing
    // now and reopening for task-2 would remount `CancelCleaningTaskDialogBody`,
    // whose mount effect calls `mutation.reset()` on the very same shared mutation
    // object task-1's still in-flight request is bound to.
    fireEvent.click(screen.getByRole("button", { name: "Cancelar limpieza" }));
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(cancelTask).toHaveBeenCalledTimes(1);

    // Every row's button (unreachable behind the still-open modal above) is also
    // disabled at the DOM level — `CleaningTaskRow`'s own guard, queryable directly
    // once we bypass the accessible-tree hiding, mirroring
    // `AssignCleanerControl.isBlocked`.
    for (const button of screen.getAllByRole("button", {
      name: "Cancelar",
      hidden: true,
    })) {
      expect(button).toBeDisabled();
    }
  });
});
