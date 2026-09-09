import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { CleaningTaskStatus, CleaningValidationStatus } from "../data";
import { ValidateCleaningControl } from "./validate-cleaning-control";

function renderControl(
  overrides: Partial<React.ComponentProps<typeof ValidateCleaningControl>> = {},
  locale: "es" | "en" = "es",
) {
  const onValidate = overrides.onValidate ?? vi.fn();
  const result = render(
    <I18nProvider locale={locale}>
      <ValidateCleaningControl
        taskId="task-1"
        status="COMPLETED"
        validationStatus="PENDING"
        isPending={false}
        isBlocked={false}
        {...overrides}
        onValidate={onValidate}
      />
    </I18nProvider>,
  );
  return { ...result, onValidate };
}

const validar = () => screen.getByRole("button", { name: "Validar" });
const noPasa = () => screen.getByRole("button", { name: "No pasa" });

describe("ValidateCleaningControl — visibility (R3.1)", () => {
  it.each([
    "CREATED",
    "ASSIGNED",
    "ACCEPTED",
    "REJECTED",
    "IN_PROGRESS",
    "PENDING_REVIEW",
    "FAILED",
    "CANCELLED",
  ] as const)("renders nothing when status is %s", (status: CleaningTaskStatus) => {
    const { container } = renderControl({ status });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders both buttons when status is COMPLETED, with or without a prior verdict", () => {
    renderControl({ status: "COMPLETED" });
    expect(validar()).toBeInTheDocument();
    expect(noPasa()).toBeInTheDocument();
  });

  it("still renders when a verdict already exists — the control does not disappear (amendment R3.1)", () => {
    renderControl({ status: "COMPLETED", validationStatus: "FAILED" });
    expect(validar()).toBeInTheDocument();
    expect(noPasa()).toBeInTheDocument();
  });
});

describe("ValidateCleaningControl — the vigent verdict cannot be resent (R3.6)", () => {
  it("disables 'Validar' when the task is already PASSED, keeps 'No pasa' enabled", () => {
    renderControl({ validationStatus: "PASSED" });
    expect(validar()).toBeDisabled();
    expect(noPasa()).toBeEnabled();
  });

  it("disables 'No pasa' when the task is already FAILED, keeps 'Validar' enabled", () => {
    renderControl({ validationStatus: "FAILED" });
    expect(noPasa()).toBeDisabled();
    expect(validar()).toBeEnabled();
  });

  it("both buttons are operable before any verdict exists", () => {
    const { onValidate } = renderControl({ validationStatus: "PENDING" });
    expect(validar()).toBeEnabled();
    expect(noPasa()).toBeEnabled();

    fireEvent.click(validar());
    expect(onValidate).toHaveBeenCalledExactlyOnceWith({
      taskId: "task-1",
      verdict: "PASSED",
    });
  });

  it("sends FAILED when 'No pasa' is clicked", () => {
    const { onValidate } = renderControl({ validationStatus: "PENDING" });
    fireEvent.click(noPasa());
    expect(onValidate).toHaveBeenCalledExactlyOnceWith({
      taskId: "task-1",
      verdict: "FAILED",
    });
  });
});

describe("ValidateCleaningControl — in-flight state", () => {
  it("disables both buttons while this row's write is in flight", () => {
    renderControl({ isPending: true });
    expect(validar()).toBeDisabled();
    expect(noPasa()).toBeDisabled();
  });

  it("disables both buttons while another row's write is in flight", () => {
    renderControl({ isBlocked: true });
    expect(validar()).toBeDisabled();
    expect(noPasa()).toBeDisabled();
  });
});

describe("ValidateCleaningControl — the static notice (R3.4)", () => {
  it("states both consequences as static text, not a title", () => {
    renderControl();
    const notice = screen.getByText(
      "«No pasa» notifica a la limpiadora asignada. Validar no cambia el estado de la vivienda.",
    );
    expect(notice).toBeInTheDocument();
    expect(notice.tagName).toBe("P");
    expect(validar()).not.toHaveAttribute("title");
    expect(noPasa()).not.toHaveAttribute("title");
  });

  it("associates the notice with both buttons via aria-describedby", () => {
    renderControl();
    const notice = screen.getByText(/notifica a la limpiadora/);
    expect(validar()).toHaveAttribute("aria-describedby", notice.id);
    expect(noPasa()).toHaveAttribute("aria-describedby", notice.id);
  });

  it("renders the notice in English too", () => {
    renderControl({}, "en");
    expect(
      screen.getByText(
        "\"Does not pass\" notifies the assigned cleaner. Validating does not change the property's state.",
      ),
    ).toBeInTheDocument();
  });
});

describe("ValidateCleaningControl — locale and accessibility", () => {
  it("renders the English catalog", () => {
    renderControl({}, "en");
    expect(screen.getByRole("button", { name: "Validate" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Does not pass" }),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderControl();
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("has no accessibility violations with a prior verdict and one button disabled", async () => {
    const { container } = renderControl({ validationStatus: "PASSED" as CleaningValidationStatus });
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
