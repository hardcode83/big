import { describe, expect, it } from "vitest";

import { render, screen } from "@/test/render";
import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("exposes its text content as the accessible name", () => {
    render(<Button>Guardar</Button>);
    expect(screen.getByRole("button", { name: "Guardar" })).toBeInTheDocument();
  });

  it("is focusable via the keyboard", () => {
    render(<Button>Guardar</Button>);
    const button = screen.getByRole("button", { name: "Guardar" });
    button.focus();
    expect(button).toHaveFocus();
  });

  it("renders as its child element when asChild is set", () => {
    render(
      <Button asChild>
        <a href="/destino">Ir</a>
      </Button>,
    );
    expect(screen.getByRole("link", { name: "Ir" })).toHaveAttribute(
      "href",
      "/destino",
    );
  });

  it("is disabled when disabled is set", () => {
    render(<Button disabled>Guardar</Button>);
    expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
  });

  it("keeps its accessible name/role when glow is set", () => {
    render(<Button glow>Guardar</Button>);
    expect(screen.getByRole("button", { name: "Guardar" })).toBeInTheDocument();
  });
});
