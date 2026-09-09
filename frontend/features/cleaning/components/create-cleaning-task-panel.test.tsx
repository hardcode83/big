import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UseMutationResult } from "@tanstack/react-query";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen } from "@/test/render";

import type {
  CleaningTask,
  CreateCleaningTaskInput,
  PropertySummary,
} from "../data";
import { CreateCleaningTaskPanel } from "./create-cleaning-task-panel";

const AWAITING_UUID = "8f14e45f-ceea-467a-9b7c-9d7c1a2b3c4d";
const OCCUPIED_UUID = "2b7e1516-28ae-4d2a-a6ab-f7158809cf4f";
const UNRESOLVED_UUID = "c9f0f895-fb98-4b41-a54b-2e1a7c0d9e8f";

const properties: PropertySummary[] = [
  {
    id: AWAITING_UUID,
    name: "Redes 11",
    internalCode: "REDES11",
    currentOperationalState: "AWAITING_CLEANING",
  },
  {
    id: OCCUPIED_UUID,
    name: "Pajaritos 8",
    internalCode: "PAJARITOS8",
    currentOperationalState: "OCCUPIED_ESTIMATED",
  },
  // R2.3, fail-open: an id whose operational state could not be resolved — the
  // same shape the backend hands out as "nothing known", never actually
  // `undefined` on the wire, but exercised here the way `warnsNotAssignable`
  // itself is unit-tested: as the type allows but this catalog cannot promise.
  {
    id: UNRESOLVED_UUID,
    name: "Costa 3",
    internalCode: "COSTA3",
    currentOperationalState: undefined,
  } as unknown as PropertySummary,
];

const propertyDirectoryResult = vi.hoisted(() => ({
  current: {
    data: undefined as PropertySummary[] | undefined,
    isPending: false,
  },
}));

vi.mock("../hooks/use-cleaning-data", () => ({
  usePropertyDirectory: () => propertyDirectoryResult.current,
}));

function makeMutation(
  overrides: Partial<
    UseMutationResult<CleaningTask, Error, CreateCleaningTaskInput>
  > = {},
) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    ...overrides,
  } as unknown as UseMutationResult<CleaningTask, Error, CreateCleaningTaskInput>;
}

function renderPanel(
  mutation: UseMutationResult<CleaningTask, Error, CreateCleaningTaskInput>,
  open = true,
) {
  const onOpenChange = vi.fn();
  const utils = render(
    <I18nProvider locale="es">
      <CreateCleaningTaskPanel
        open={open}
        onOpenChange={onOpenChange}
        mutation={mutation}
      />
    </I18nProvider>,
  );
  return { ...utils, onOpenChange };
}

beforeEach(() => {
  propertyDirectoryResult.current = { data: properties, isPending: false };
});

describe("CreateCleaningTaskPanel — the toggle (design D1)", () => {
  it("starts collapsed and expands the form when the button is pressed", () => {
    const onOpenChange = vi.fn();
    render(
      <I18nProvider locale="es">
        <CreateCleaningTaskPanel
          open={false}
          onOpenChange={onOpenChange}
          mutation={makeMutation()}
        />
      </I18nProvider>,
    );

    expect(screen.queryByLabelText("Vivienda de la nueva tarea")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nueva limpieza" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("renders the form fields when open, and no reservation selector (R1.2, ASSUMPTION 2)", () => {
    renderPanel(makeMutation());

    expect(screen.getByLabelText("Vivienda de la nueva tarea")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Inicio programado (opcional)"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Fin programado (opcional)"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/reserva/i)).not.toBeInTheDocument();
  });
});

describe("CreateCleaningTaskPanel — what it sends (R1.2, R1.3)", () => {
  it("omits both scheduled fields from the body when left empty", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    expect(mutation.mutate).toHaveBeenCalledExactlyOnceWith(
      { propertyId: AWAITING_UUID },
      expect.anything(),
    );
    const [input] = (mutation.mutate as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(input).not.toHaveProperty("scheduledStart");
    expect(input).not.toHaveProperty("scheduledEnd");
  });

  it("converts both datetime-local fields with toISOString, the tech-eta-field mechanism", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });
    fireEvent.change(screen.getByLabelText("Inicio programado (opcional)"), {
      target: { value: "2026-09-10T09:00" },
    });
    fireEvent.change(screen.getByLabelText("Fin programado (opcional)"), {
      target: { value: "2026-09-10T11:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    const [input] = (mutation.mutate as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(input.propertyId).toBe(AWAITING_UUID);
    expect(input.scheduledStart).toBe(
      new Date("2026-09-10T09:00").toISOString(),
    );
    expect(input.scheduledEnd).toBe(
      new Date("2026-09-10T11:00").toISOString(),
    );
  });

  it("never sends a reservation id — there is no such field to fill (ASSUMPTION 2)", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    const [input] = (mutation.mutate as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(Object.keys(input).sort()).toEqual(["propertyId"]);
  });

  it("does not submit without a chosen property", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    expect(mutation.mutate).not.toHaveBeenCalled();
  });
});

describe("CreateCleaningTaskPanel — the non-assignability notice (R2.1–R2.3)", () => {
  it("shows the warning for a property whose state does not admit CLEANER_ASSIGNED", () => {
    renderPanel(makeMutation());

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: OCCUPIED_UUID },
    });

    expect(
      screen.getByText(/no podrá asignarse hasta que la vivienda esté/),
    ).toBeInTheDocument();
  });

  it("hides the warning for a property awaiting cleaning", () => {
    renderPanel(makeMutation());

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });

    expect(
      screen.queryByText(/no podrá asignarse hasta que la vivienda esté/),
    ).not.toBeInTheDocument();
  });

  it("fails open — no warning — when the state could not be resolved (R2.3)", () => {
    renderPanel(makeMutation());

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: UNRESOLVED_UUID },
    });

    expect(
      screen.queryByText(/no podrá asignarse hasta que la vivienda esté/),
    ).not.toBeInTheDocument();
  });

  it("never blocks submission while the warning is visible (R2.2)", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: OCCUPIED_UUID },
    });
    expect(
      screen.getByText(/no podrá asignarse hasta que la vivienda esté/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Crear" }));
    expect(mutation.mutate).toHaveBeenCalledExactlyOnceWith(
      { propertyId: OCCUPIED_UUID },
      expect.anything(),
    );
  });

  it("offers no manual property-state transition of any kind (R2.4)", () => {
    renderPanel(makeMutation());

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: OCCUPIED_UUID },
    });

    expect(
      screen.queryByRole("button", { name: /estado/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /estado/i })).not.toBeInTheDocument();
  });
});

describe("CreateCleaningTaskPanel — double-submit guard (like the dashboard's cancel dialog)", () => {
  it("blocks a second submit fired before the mutation settles", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });
    const button = screen.getByRole("button", { name: "Crear" });
    fireEvent.click(button);
    fireEvent.click(button);

    expect(mutation.mutate).toHaveBeenCalledTimes(1);
  });

  it("allows a new submit once the mutation has settled", () => {
    const mutation = makeMutation();
    renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });
    const button = screen.getByRole("button", { name: "Crear" });
    fireEvent.click(button);

    // Simulate the mutation settling by invoking the `onSettled` callback the
    // component passed to `mutate`, exactly as the real hook would call it.
    const [, options] = (mutation.mutate as ReturnType<typeof vi.fn>).mock
      .calls[0];
    options.onSettled();

    fireEvent.click(button);
    expect(mutation.mutate).toHaveBeenCalledTimes(2);
  });

  it("closes the panel through onOpenChange when the mutation succeeds", () => {
    const mutation = makeMutation();
    const { onOpenChange } = renderPanel(mutation);

    fireEvent.change(screen.getByLabelText("Vivienda de la nueva tarea"), {
      target: { value: AWAITING_UUID },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    const [, options] = (mutation.mutate as ReturnType<typeof vi.fn>).mock
      .calls[0];
    options.onSuccess();

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows the sending label while the mutation is pending", () => {
    renderPanel(makeMutation({ isPending: true }));

    expect(screen.getByRole("button", { name: "Creando…" })).toBeDisabled();
  });
});
