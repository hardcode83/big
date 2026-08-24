import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { getA11yViolations, render, screen } from "@/test/render";

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

import type {
  CleanerSummary,
  CleaningTaskListItem,
  PropertySummary,
} from "../data";
import { buildDirectory } from "../lib/directory";
import { CleaningTaskRow } from "./cleaning-task-row";

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
  // The default row is assignable, so the pre-existing tests keep describing the ordinary
  // case. The blocked shapes are posed explicitly by the tests that are about them.
  assignmentBlockedBy: null,
};

const properties: PropertySummary[] = [
  { id: PROPERTY_UUID, name: "Redes 11", internalCode: "REDES11" },
];
const cleaners: CleanerSummary[] = [
  { id: CLEANER_UUID, name: "Marta Ruiz", isActive: true },
  { id: "inactive-1", name: "Ana Pérez", isActive: false },
];

function settled<T extends { id: string }>(entries: readonly T[]) {
  return { index: buildDirectory(entries), isPending: false };
}
/** A catalog with nothing in it: in flight when `isPending`, failed when not. */
function absent<T extends { id: string }>(isPending: boolean) {
  return { index: buildDirectory<T>(undefined), isPending };
}

function renderRow(overrides: Partial<React.ComponentProps<typeof CleaningTaskRow>> = {}) {
  const props = {
    task,
    properties: settled(properties),
    cleaners: settled(cleaners),
    ...overrides,
  };
  return render(
    <I18nProvider locale="es">
      <ul>
        <CleaningTaskRow {...props} />
      </ul>
    </I18nProvider>,
  );
}

beforeEach(() => {
  role.current = "PROPERTY_MANAGER";
});

describe("CleaningTaskRow (R2.1, R2.2, R1.6, R5.2)", () => {
  it("names the property by internal code and name, never by its id (R2.1)", () => {
    const { container } = renderRow();
    expect(screen.getByText(/REDES11 · Redes 11/)).toBeInTheDocument();
    // `innerHTML`, not `textContent`: an id smuggled into an attribute
    // (aria-label, title, a select value) must fail this too.
    expect(container.innerHTML).not.toContain(PROPERTY_UUID);
  });

  it("names the cleaner, never her id (R2.2)", () => {
    const { container } = renderRow();
    expect(screen.getByText("Marta Ruiz")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain(CLEANER_UUID);
  });

  it("resolves an inactive cleaner's name just as well (design D4)", () => {
    renderRow({
      task: { ...task, assignedCleanerId: "inactive-1" },
    });
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
  });

  it("says unassigned for a null cleaner, distinct from a load failure (R2.3)", () => {
    renderRow({ task: { ...task, assignedCleanerId: null } });
    expect(screen.getByText("Sin asignar")).toBeInTheDocument();
    expect(screen.queryByText("Identidad no disponible")).not.toBeInTheDocument();
  });

  it("degrades an unresolvable cleaner and leaves the rest of the row intact (R2.4)", () => {
    const { container } = renderRow({
      task: { ...task, assignedCleanerId: "gone-1" },
    });

    expect(screen.getByText("Identidad no disponible")).toBeInTheDocument();
    expect(screen.queryByText("Sin asignar")).not.toBeInTheDocument();
    // The rest of the row still renders.
    expect(screen.getByText(/REDES11 · Redes 11/)).toBeInTheDocument();
    expect(screen.getByText("Asignada")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("gone-1");
  });

  it("degrades an unresolvable property without breaking the row (R2.4)", () => {
    renderRow({ properties: settled([]) });
    expect(screen.getByText("Identidad no disponible")).toBeInTheDocument();
    expect(screen.getByText("Marta Ruiz")).toBeInTheDocument();
  });

  it("shows a neutral marker while a catalog is still in flight (design D5)", () => {
    const { container } = renderRow({
      cleaners: absent<CleanerSummary>(true),
      properties: absent<PropertySummary>(true),
    });

    expect(screen.getAllByText("Cargando identidad…").length).toBe(2);
    expect(screen.queryByText("Identidad no disponible")).not.toBeInTheDocument();
    expect(screen.queryByText("Sin asignar")).not.toBeInTheDocument();
    expect(container.innerHTML).not.toContain(CLEANER_UUID);
  });

  it("degrades to unavailable — not to pending — when a catalog failed (design D5)", () => {
    renderRow({
      cleaners: absent<CleanerSummary>(false),
    });
    expect(screen.getByText("Identidad no disponible")).toBeInTheDocument();
    expect(screen.queryByText("Cargando identidad…")).not.toBeInTheDocument();
  });

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
  ] as const)("shows %s as its translated label, never the raw enum (R1.6)", (status, label) => {
    const { container } = renderRow({ task: { ...task, status } });
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.textContent).not.toContain(status);
  });

  it("says so explicitly when a task has no schedule", () => {
    renderRow({
      task: { ...task, scheduledStart: null, scheduledEnd: null },
    });
    expect(screen.getAllByText("Sin programar").length).toBe(2);
  });

  it("renders the English catalog when the locale is en (R5.1)", () => {
    render(
      <I18nProvider locale="en">
        <ul>
          <CleaningTaskRow
            task={{ ...task, assignedCleanerId: null }}
            properties={settled(properties)}
            cleaners={settled(cleaners)}
          />
        </ul>
      </I18nProvider>,
    );
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    expect(screen.getByText("Assigned")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderRow();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("CleaningTaskRow — who gets the assignment control (R4.3)", () => {
  const assignment = { isPending: false, isBlocked: false, onConfirm: () => {} };

  it("renders the control for a PROPERTY_MANAGER, alongside the current assignment", () => {
    renderRow({ assignment });
    expect(
      screen.getByRole("combobox", { name: "Asignar limpiadora" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Asignar" })).toBeInTheDocument();
    // R2.2 holds for the manager too: she can read who is assigned right now. Her
    // name also appears as a candidate <option>, so the assertion is that at least
    // one occurrence is the read-only statement rather than a dropdown entry.
    expect(
      screen
        .getAllByText("Marta Ruiz")
        .some((node) => node.tagName !== "OPTION"),
    ).toBe(true);
  });

  it("keeps the name as read-only text for a TENANT_OWNER (R4.3)", () => {
    role.current = "TENANT_OWNER";
    renderRow({ assignment });
    expect(screen.getByText("Marta Ruiz")).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Asignar limpiadora" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Asignar" }),
    ).not.toBeInTheDocument();
  });

  it("stays read-only text when the view offers no assignment at all", () => {
    renderRow();
    expect(screen.getByText("Marta Ruiz")).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Asignar limpiadora" }),
    ).not.toBeInTheDocument();
  });

  it("puts no id anywhere in the manager's render except the control's form values (R2.2)", () => {
    const { container } = renderRow({ assignment });

    // The manager's render is the only one that carries ids at all, so the guard has
    // to run here — the read-only renders above cannot catch a regression in this
    // branch.
    //
    // The exemption is one **attribute**, not a whole element: `<option value>` is a
    // form transport value and is allowed to be an id. Exempting the element instead
    // would skip its every other attribute, and a UUID in `aria-label` or `title` is
    // read out verbatim by a screen reader — precisely the leak this guard exists to
    // catch.
    const isAllowed = (node: Element, attribute: Attr) =>
      node.tagName === "OPTION" && attribute.name === "value";

    for (const node of Array.from(container.querySelectorAll("*"))) {
      for (const attribute of Array.from(node.attributes)) {
        if (isAllowed(node, attribute)) {
          continue;
        }
        const where = `<${node.tagName.toLowerCase()} ${attribute.name}>`;
        expect(attribute.value, where).not.toContain(CLEANER_UUID);
        expect(attribute.value, where).not.toContain(PROPERTY_UUID);
      }
    }
    // And no id is ever visible text, control or no control.
    expect(container.textContent).not.toContain(CLEANER_UUID);
    expect(container.textContent).not.toContain(PROPERTY_UUID);
  });

  it("offers only active cleaners, though an inactive one still resolves her name (R4.2, D4)", () => {
    renderRow({
      assignment,
      task: { ...task, assignedCleanerId: "inactive-1" },
    });
    expect(
      screen.queryByRole("option", { name: "Ana Pérez" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Marta Ruiz" })).toBeInTheDocument();
  });
});

describe("CleaningTaskRow passes the pre-flight through (R3.1, design D9)", () => {
  it("hands the blocker to the control instead of deriving anything", () => {
    renderRow({
      task: { ...task, assignmentBlockedBy: "PROPERTY_STATE" },
      assignment: { isPending: false, isBlocked: false, onConfirm: vi.fn() },
    });

    expect(
      screen.getByText(
        "No se puede asignar todavía: la vivienda no está pendiente de limpieza.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Asignar" })).toBeDisabled();
  });

  it("leaves the control alone when nothing is blocking", () => {
    renderRow({
      task: { ...task, assignmentBlockedBy: null },
      assignment: { isPending: false, isBlocked: false, onConfirm: vi.fn() },
    });

    expect(screen.queryByText(/No se puede asignar/)).not.toBeInTheDocument();
    // Still disabled, but for the ordinary reason: nobody has been picked yet.
    expect(screen.getByRole("button", { name: "Asignar" })).toBeDisabled();
  });

  it("shows the task-status cause with its own sentence", () => {
    renderRow({
      task: { ...task, status: "IN_PROGRESS", assignmentBlockedBy: "TASK_STATUS" },
      assignment: { isPending: false, isBlocked: false, onConfirm: vi.fn() },
    });

    expect(
      screen.getByText(
        "No se puede asignar: esta tarea ya no admite un cambio de asignación.",
      ),
    ).toBeInTheDocument();
  });

  it("says nothing about it to a role without the control (R4.3)", () => {
    // The row still states who is assigned, but a blocked-assignment hint on a screen with
    // no assignment control would be explaining an action this role cannot take.
    role.current = "CLEANER";
    renderRow({ task: { ...task, assignmentBlockedBy: "PROPERTY_STATE" } });

    expect(screen.queryByText(/No se puede asignar/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Asignar" })).not.toBeInTheDocument();
  });

  it("has no accessibility violations with a blocked row", async () => {
    const { container } = renderRow({
      task: { ...task, assignmentBlockedBy: "PROPERTY_STATE" },
      assignment: { isPending: false, isBlocked: false, onConfirm: vi.fn() },
    });

    expect(await getA11yViolations(container)).toEqual([]);
  });
});
