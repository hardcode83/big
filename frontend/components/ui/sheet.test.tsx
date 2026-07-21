import { describe, expect, it } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";

function Example() {
  return (
    <Sheet>
      <SheetTrigger>Abrir</SheetTrigger>
      <SheetContent side="right" closeLabel="Cerrar">
        <SheetTitle>Panel</SheetTitle>
        <SheetDescription>Contenido del panel</SheetDescription>
      </SheetContent>
    </Sheet>
  );
}

describe("Sheet", () => {
  it("opens from its trigger and exposes a dialog", async () => {
    render(<Example />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("renders a close button with the provided localized label", async () => {
    render(<Example />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir" }));
    await screen.findByRole("dialog");
    expect(screen.getByRole("button", { name: "Cerrar" })).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    render(<Example />);
    const trigger = screen.getByRole("button", { name: "Abrir" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
