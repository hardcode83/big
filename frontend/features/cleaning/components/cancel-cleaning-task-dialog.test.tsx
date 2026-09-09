import type {
  MutationFunctionContext,
  UseMutateFunction,
  UseMutationResult,
} from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { CleaningTask } from "../data";
import type { CancelCleaningTaskInput } from "../hooks/use-cancel-cleaning-task";
import { CancelCleaningTaskDialog } from "./cancel-cleaning-task-dialog";

type Mutation = UseMutationResult<CleaningTask, Error, CancelCleaningTaskInput>;

function buildMutation(overrides: Partial<Mutation> = {}): Mutation {
  return {
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    data: undefined,
    ...overrides,
  } as unknown as Mutation;
}

function renderDialog(
  overrides: {
    mutation?: Mutation;
    onOpenChange?: (open: boolean) => void;
  } = {},
  locale: "es" | "en" = "es",
) {
  const mutation = overrides.mutation ?? buildMutation();
  const onOpenChange = overrides.onOpenChange ?? vi.fn();
  const result = render(
    <I18nProvider locale={locale}>
      <CancelCleaningTaskDialog
        open
        onOpenChange={onOpenChange}
        taskId="task-1"
        mutation={mutation}
      />
    </I18nProvider>,
  );
  return { ...result, mutation, onOpenChange };
}

const confirm = () => screen.getByRole("button", { name: "Confirmar cancelación" });

describe("CancelCleaningTaskDialog — submitting a reason (R4.1, R4.2)", () => {
  it("submits exactly once with the trimmed reason and no other field (R4.2)", () => {
    const { mutation } = renderDialog();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  se rompió la caldera  " },
    });
    fireEvent.click(confirm());
    expect(mutation.mutate).toHaveBeenCalledExactlyOnceWith(
      { taskId: "task-1", reason: "se rompió la caldera" },
      expect.any(Object),
    );
  });

  it("does not submit when the reason is whitespace-only", () => {
    const { mutation } = renderDialog();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(mutation.mutate).not.toHaveBeenCalled();
  });

  it("hard-caps the textarea at 500 chars via maxLength, disabling submit past it", () => {
    renderDialog();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "x".repeat(501) } });
    expect(confirm()).toBeDisabled();
  });

  it("dispatches one mutation for two clicks in the same frame (double-submit guard)", () => {
    const { mutation } = renderDialog();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    fireEvent.click(confirm());
    fireEvent.click(confirm());
    expect(mutation.mutate).toHaveBeenCalledTimes(1);
  });
});

describe("CancelCleaningTaskDialog — the replacement-task notice (R4.4)", () => {
  it("warns that cancelling may create a replacement task", () => {
    renderDialog();
    expect(
      screen.getByText(
        "Cancelar esta limpieza puede crear una tarea de reemplazo sin asignar.",
      ),
    ).toBeInTheDocument();
  });
});

describe("CancelCleaningTaskDialog — closes on success, stays open on failure (design D4, R4.5)", () => {
  it("closes the dialog when the mutation resolves", () => {
    const mutate: UseMutateFunction<
      CleaningTask,
      Error,
      CancelCleaningTaskInput
    > = vi.fn((_input, options) => {
      options?.onSuccess?.(
        {} as CleaningTask,
        _input,
        undefined,
        {} as MutationFunctionContext,
      );
    });
    const onOpenChange = vi.fn();
    renderDialog({ mutation: buildMutation({ mutate }), onOpenChange });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    fireEvent.click(confirm());
    expect(onOpenChange).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("renders the terminal-conflict copy and keeps the form on screen (R4.5, design D8)", () => {
    renderDialog({
      mutation: buildMutation({
        isError: true,
        error: new ApiError({ code: "CONFLICT", message: "boom", status: 409 }),
      }),
    });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("Esa tarea ya está cerrada; no se puede cancelar.");
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(confirm()).toBeInTheDocument();
  });

  it("distinguishes the property-state 409 from the terminal one (R4.5, design D8)", () => {
    renderDialog({
      mutation: buildMutation({
        isError: true,
        error: new ApiError({
          code: "PROPERTY_STATE_CONFLICT",
          message: "boom",
          status: 409,
        }),
      }),
    });
    expect(screen.getByRole("alert").textContent).toBe(
      "El estado de la vivienda impide cancelar esta limpieza ahora mismo.",
    );
  });

  it.each([
    [403, "No tienes permiso para cancelar limpiezas."],
    [404, "Esa tarea de limpieza ya no existe."],
    [500, "No se pudo cancelar la limpieza. Vuelve a intentarlo."],
  ] as const)("maps status %s to its own copy", (status, message) => {
    renderDialog({
      mutation: buildMutation({
        isError: true,
        error: new ApiError({ code: "CODE", message: "backend detail", status }),
      }),
    });
    expect(screen.getByRole("alert").textContent).toBe(message);
  });

  it("never paints the backend's technical message", () => {
    const { container } = renderDialog({
      mutation: buildMutation({
        isError: true,
        error: new ApiError({
          code: "CONFLICT",
          message: "guest still inside",
          status: 409,
        }),
      }),
    });
    expect(container.textContent).not.toContain("guest still inside");
  });
});

describe("CancelCleaningTaskDialog — a fresh open discards stale mutation state", () => {
  it("calls mutation.reset() once on mount", () => {
    const reset = vi.fn();
    renderDialog({ mutation: buildMutation({ reset }) });
    expect(reset).toHaveBeenCalledTimes(1);
  });
});

describe("CancelCleaningTaskDialog — the character-count hint (fix round, Finding 3, i18n)", () => {
  it("renders the remaining count through a locale key, not a hardcoded literal", () => {
    renderDialog();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "motivo" } });
    // REASON_MAX (500) - "motivo".length (6) = 494. The parentheses come from the
    // `cancel.reason.charsRemaining` locale value ("({{count}})"), not JSX literals.
    expect(screen.getByText("(494)")).toBeInTheDocument();
  });

  it("renders the English catalog's own formatting", () => {
    renderDialog({}, "en");
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "reason" } });
    expect(screen.getByText("(494)")).toBeInTheDocument();
  });
});

describe("CancelCleaningTaskDialog — blocks dismissal while pending (fix round, Finding 1, D4)", () => {
  it("ignores the sheet's own close button while the mutation is pending", () => {
    const onOpenChange = vi.fn();
    renderDialog({ mutation: buildMutation({ isPending: true }), onOpenChange });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar limpieza" }));
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("ignores Escape while the mutation is pending", () => {
    const onOpenChange = vi.fn();
    renderDialog({ mutation: buildMutation({ isPending: true }), onOpenChange });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("still forwards a close request once the mutation has settled", () => {
    const onOpenChange = vi.fn();
    renderDialog({ mutation: buildMutation({ isPending: false }), onOpenChange });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar limpieza" }));
    expect(onOpenChange).toHaveBeenCalledExactlyOnceWith(false);
  });
});

describe("CancelCleaningTaskDialog — locale and accessibility", () => {
  it("renders the English catalog", () => {
    renderDialog({}, "en");
    expect(
      screen.getByRole("button", { name: "Confirm cancellation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Cancelling may create a replacement task without an assigned cleaner.",
      ),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderDialog();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
