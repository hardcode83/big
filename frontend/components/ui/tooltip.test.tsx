import { describe, expect, it } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

function Example() {
  return (
    <TooltipProvider delayDuration={0}>
      <Tooltip>
        <TooltipTrigger>Ayuda</TooltipTrigger>
        <TooltipContent>Texto de ayuda</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

describe("Tooltip", () => {
  it("exposes a focusable trigger with an accessible name", () => {
    render(<Example />);
    const trigger = screen.getByRole("button", { name: "Ayuda" });
    trigger.focus();
    expect(trigger).toHaveFocus();
  });

  it("reveals its content when the trigger receives focus", async () => {
    render(<Example />);
    fireEvent.focus(screen.getByRole("button", { name: "Ayuda" }));
    const matches = await screen.findAllByText("Texto de ayuda");
    expect(matches.length).toBeGreaterThan(0);
  });
});
