import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { StatePanel } from "@/components/states/state-panel";

describe("StatePanel (D8)", () => {
  it("renders the title at the requested heading level", () => {
    render(<StatePanel title="Título" headingLevel={1} />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Título" }),
    ).toBeInTheDocument();
  });
});

describe("LoadingState (D8)", () => {
  it("is a busy status region with an accessible label", () => {
    render(<LoadingState label="Cargando…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Cargando…")).toBeInTheDocument();
  });

  it("is not an alert", () => {
    render(<LoadingState label="Cargando…" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ErrorState (D8)", () => {
  it("is an alert region", () => {
    render(<ErrorState title="Error" description="Falló" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows no retry button without a reset callback", () => {
    render(<ErrorState title="Error" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows retry only with a real callback and calls it", () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Error" onRetry={onRetry} retryLabel="Reintentar" />);
    const button = screen.getByRole("button", { name: "Reintentar" });
    fireEvent.click(button);
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("is not busy", () => {
    render(<ErrorState title="Error" />);
    expect(screen.getByRole("alert")).not.toHaveAttribute("aria-busy", "true");
  });
});

describe("EmptyState (D8)", () => {
  it("renders neutral content with no alert or busy semantics", () => {
    render(<EmptyState title="Sin resultados" description="Nada aquí" />);
    expect(screen.getByText("Sin resultados")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders an optional action supplied by a feature", () => {
    render(
      <EmptyState
        title="Sin resultados"
        action={<button type="button">Crear</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Crear" })).toBeInTheDocument();
  });
});
