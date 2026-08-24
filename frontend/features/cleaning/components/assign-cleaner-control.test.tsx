import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { CleanerSummary } from "../data";
import { AssignCleanerControl } from "./assign-cleaner-control";

const cleaners: CleanerSummary[] = [
  { id: "active-1", name: "Marta Ruiz", isActive: true },
  { id: "active-2", name: "Lucía Gil", isActive: true },
  { id: "inactive-1", name: "Ana Pérez", isActive: false },
];

function renderControl(
  overrides: Partial<React.ComponentProps<typeof AssignCleanerControl>> = {},
  locale: "es" | "en" = "es",
) {
  const onConfirm = overrides.onConfirm ?? vi.fn();
  const result = render(
    <I18nProvider locale={locale}>
      <AssignCleanerControl
        taskId="task-1"
        currentCleanerId={null}
        cleaners={cleaners}
        isPending={false}
        isBlocked={false}
        blockedBy={null}
        {...overrides}
        onConfirm={onConfirm}
      />
    </I18nProvider>,
  );
  return { ...result, onConfirm };
}

const select = () => screen.getByRole("combobox", { name: "Asignar limpiadora" });
const confirm = () => screen.getByRole("button", { name: "Asignar" });

describe("AssignCleanerControl (R4.1, R4.2, R5.1, R5.3, design D8)", () => {
  it("offers only active cleaners as candidates (R4.2)", () => {
    renderControl();
    expect(screen.getByRole("option", { name: "Marta Ruiz" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Lucía Gil" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Ana Pérez" })).not.toBeInTheDocument();
  });

  it("does not confirm on `change`, only on the button (design D8)", () => {
    const { onConfirm } = renderControl();

    fireEvent.change(select(), { target: { value: "active-2" } });
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(confirm());
    expect(onConfirm).toHaveBeenCalledExactlyOnceWith({
      taskId: "task-1",
      cleanerId: "active-2",
    });
  });

  it("cannot confirm with nothing chosen", () => {
    const { onConfirm } = renderControl();
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("starts empty even on an assigned task, so one stray click cannot assign (R4.1)", () => {
    const { onConfirm } = renderControl({ currentCleanerId: "active-1" });
    expect(select()).toHaveValue("");
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("refuses to re-send the cleaner the task already has", () => {
    const { onConfirm } = renderControl({ currentCleanerId: "active-1" });
    fireEvent.change(select(), { target: { value: "active-1" } });
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("confirms a genuine reassignment", () => {
    const { onConfirm } = renderControl({ currentCleanerId: "active-1" });
    fireEvent.change(select(), { target: { value: "active-2" } });
    fireEvent.click(confirm());
    expect(onConfirm).toHaveBeenCalledExactlyOnceWith({
      taskId: "task-1",
      cleanerId: "active-2",
    });
  });

  it("locks both controls and says so while this row's write is in flight", () => {
    renderControl({ isPending: true, isBlocked: true });
    expect(select()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Asignando…" })).toBeDisabled();
  });

  it("blocks only confirming while ANOTHER row's write is in flight (R4.4/R4.5, R5.3)", () => {
    renderControl({ isPending: false, isBlocked: true });
    expect(confirm()).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Asignando…" }),
    ).not.toBeInTheDocument();
    // The select stays enabled and focusable: disabling a focused element drops
    // focus to <body>, which would strand a keyboard user mid-pick (R5.3).
    expect(select()).toBeEnabled();
    select().focus();
    expect(select()).toHaveFocus();
    fireEvent.change(select(), { target: { value: "active-1" } });
    expect(select()).toHaveValue("active-1");
  });

  it("keeps a focused select focused when another row's write starts (R5.3)", () => {
    const { rerender } = renderControl({ isPending: false, isBlocked: false });
    select().focus();
    expect(select()).toHaveFocus();

    rerender(
      <I18nProvider locale="es">
        <AssignCleanerControl
          taskId="task-1"
          currentCleanerId={null}
          cleaners={cleaners}
          isPending={false}
          isBlocked
          blockedBy={null}
          onConfirm={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(select()).toHaveFocus();
    expect(document.activeElement).not.toBe(document.body);
  });

  it("exposes an accessible label and is operable by keyboard (R5.3)", () => {
    renderControl();
    fireEvent.change(select(), { target: { value: "active-1" } });
    for (const control of [select(), confirm()]) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(control).toHaveFocus();
    }
  });

  it("renders the English catalog when the locale is en (R5.1)", () => {
    renderControl({}, "en");
    expect(
      screen.getByRole("combobox", { name: "Assign cleaner" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign" })).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Choose a cleaner" }),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderControl();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("AssignCleanerControl blocked by the backend's pre-flight (R3.1, R3.4)", () => {
  it("disables confirm and shows the reason, associated with the button", () => {
    renderControl({ blockedBy: "PROPERTY_STATE" });

    const reason = screen.getByText(
      "No se puede asignar todavía: la vivienda no está pendiente de limpieza.",
    );
    expect(reason).toBeInTheDocument();
    expect(confirm()).toBeDisabled();
    // R3.1 asks for the motive to be *indicated*, and a visible line the button does not
    // reference is not indicated to anyone using a screen reader.
    expect(confirm()).toHaveAttribute("aria-describedby", reason.id);
  });

  it("keeps the select operable and selectable while the button is disabled (R3.4)", () => {
    // The whole reason the select is not disabled: disabling a focused element sends focus
    // to `<body>`. A manager can still choose; only sending is refused.
    renderControl({ blockedBy: "PROPERTY_STATE" });

    expect(select()).toBeEnabled();
    select().focus();
    expect(select()).toHaveFocus();
    fireEvent.change(select(), { target: { value: "active-1" } });

    expect(select()).toHaveValue("active-1");
    expect(confirm()).toBeDisabled();
  });

  it("shows a different sentence for each cause", () => {
    const { unmount } = renderControl({ blockedBy: "PROPERTY_STATE" });
    const property = screen.getByRole("button", { name: "Asignar" }).getAttribute(
      "aria-describedby",
    );
    const propertyText = document.getElementById(property ?? "")?.textContent;
    unmount();

    renderControl({ blockedBy: "TASK_STATUS" });
    const taskText = document.getElementById(
      screen.getByRole("button", { name: "Asignar" }).getAttribute(
        "aria-describedby",
      ) ?? "",
    )?.textContent;

    expect(propertyText).toBeTruthy();
    expect(taskText).toBeTruthy();
    expect(propertyText).not.toBe(taskText);
  });

  it("says nothing and describes nothing when it is not blocked", () => {
    renderControl({ blockedBy: null });

    expect(confirm()).not.toHaveAttribute("aria-describedby");
    expect(
      screen.queryByText(/No se puede asignar/),
    ).not.toBeInTheDocument();
  });

  it("still refuses to confirm even after a valid pick (R3.1)", () => {
    const { onConfirm } = renderControl({ blockedBy: "TASK_STATUS" });
    fireEvent.change(select(), { target: { value: "active-1" } });

    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());

    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("renders the reason in English too (R2.4)", () => {
    renderControl({ blockedBy: "PROPERTY_STATE" }, "en");

    expect(
      screen.getByText(
        "Cannot be assigned yet: the property is not awaiting cleaning.",
      ),
    ).toBeInTheDocument();
  });

  it.each(["es", "en"] as const)(
    "has no accessibility violations while blocked, in %s",
    async (locale) => {
      // Both locales, because the QA panel of this section noticed the blocked state was only
      // ever run through axe in Spanish. The reason line is what `aria-describedby` points at,
      // so a locale whose copy failed to render would break the association silently.
      const { container } = renderControl({ blockedBy: "PROPERTY_STATE" }, locale);

      expect(await getA11yViolations(container)).toEqual([]);
    },
  );
});
