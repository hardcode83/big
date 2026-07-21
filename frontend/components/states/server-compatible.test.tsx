import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import * as states from "@/components/states";

/**
 * Task 5.3: the state components — ModulePlaceholder especially — must remain
 * server-compatible. Rendering to static markup with no client runtime, hooks,
 * or context proves the barrel does not force a Client Component tree.
 */
describe("state components are server-compatible", () => {
  it("exposes a stable public API from the barrel", () => {
    expect(Object.keys(states).sort()).toEqual([
      "EmptyState",
      "ErrorState",
      "LoadingState",
      "ModulePlaceholder",
      "StatePanel",
    ]);
  });

  it("renders ModulePlaceholder to static markup on the server", () => {
    const html = renderToStaticMarkup(
      <states.ModulePlaceholder
        badgeLabel="En preparación"
        title="Panel"
        explanation="Prevista pero no disponible."
      />,
    );
    expect(html).toContain("Panel");
    expect(html).toContain("En preparación");
  });

  it("renders Loading, Error and Empty to static markup", () => {
    expect(() =>
      renderToStaticMarkup(<states.LoadingState label="Cargando…" />),
    ).not.toThrow();
    expect(() =>
      renderToStaticMarkup(<states.ErrorState title="Error" />),
    ).not.toThrow();
    expect(() =>
      renderToStaticMarkup(<states.EmptyState title="Vacío" />),
    ).not.toThrow();
  });
});
