import { describe, expect, it } from "vitest";

import { render, screen } from "@/test/render";
import { ModulePlaceholder } from "@/components/states/module-placeholder";

function renderPlaceholder() {
  return render(
    <ModulePlaceholder
      badgeLabel="En preparación"
      title="Panel"
      description="Vista general"
      explanation="Esta sección está prevista pero todavía no está disponible."
    />,
  );
}

describe("ModulePlaceholder (D8)", () => {
  it("shows the planned badge, title, description and explanation", () => {
    renderPlaceholder();
    expect(screen.getByText("En preparación")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Panel" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Vista general")).toBeInTheDocument();
    expect(
      screen.getByText(/prevista pero todavía no está disponible/),
    ).toBeInTheDocument();
  });

  it("is distinguishable from loading/error: no alert, no busy, no retry", () => {
    renderPlaceholder();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders no ETA, progress or business data", () => {
    const { container } = renderPlaceholder();
    expect(container.querySelector("progress")).toBeNull();
    expect(container.textContent).not.toMatch(/\d%/);
  });
});
