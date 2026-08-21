import { fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";
import { render, screen } from "@/test/render";

import { ConfirmDialog } from "./confirm-dialog";

function renderDialog() {
  const onConfirm = vi.fn();
  render(
    <ConfirmDialog
      trigger={<Button type="button">Resolver</Button>}
      title="¿Seguro?"
      description="Esto no avisa al huésped."
      confirmLabel="Sí, resolver"
      cancelLabel="Cancelar"
      onConfirm={onConfirm}
    />,
  );
  return { onConfirm, trigger: screen.getByRole("button", { name: "Resolver" }) };
}

describe("ConfirmDialog (task 7.1, D20, R5.4)", () => {
  it("stays closed until the trigger is activated", () => {
    const { onConfirm } = renderDialog();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("opens with its localized title and description", () => {
    const { trigger } = renderDialog();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("¿Seguro?");
    expect(dialog).toHaveTextContent("Esto no avisa al huésped.");
    expect(
      screen.getByRole("button", { name: "Sí, resolver" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
  });

  it("confirms once and closes", async () => {
    const { trigger, onConfirm } = renderDialog();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Sí, resolver" }));

    expect(onConfirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("cancels without confirming", async () => {
    const { trigger, onConfirm } = renderDialog();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(onConfirm).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes on Escape without confirming", async () => {
    const { trigger, onConfirm } = renderDialog();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog and returns it to the trigger on close", async () => {
    const { trigger } = renderDialog();
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});
