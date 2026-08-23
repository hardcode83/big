import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PricingTab } from "../state/use-pricing-ui-store";
import { PricingTabs } from "./pricing-tabs";

/** Static harness: the tab is controlled from outside, so the spy sees every move. */
function renderTabs(activeTab: PricingTab = "recommendations") {
  const onTabChange = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <PricingTabs activeTab={activeTab} onTabChange={onTabChange}>
        <p>Panel de {activeTab}</p>
      </PricingTabs>
    </I18nProvider>,
  );
  return { ...result, onTabChange };
}

/** Live harness: the state really moves, for the tests that check what mounts. */
function Interactive() {
  const [tab, setTab] = useState<PricingTab>("recommendations");
  return (
    <I18nProvider locale="es">
      <PricingTabs activeTab={tab} onTabChange={setTab}>
        {tab === "recommendations" ? (
          <p>contenido de recomendaciones</p>
        ) : (
          <p>contenido de reglas</p>
        )}
      </PricingTabs>
    </I18nProvider>
  );
}

const recommendationsTab = () =>
  screen.getByRole("tab", { name: "Recomendaciones" });
const rulesTab = () => screen.getByRole("tab", { name: "Reglas" });

describe("PricingTabs — structure (R1.1, design D10)", () => {
  it("exposes a tablist with two tabs and one panel", () => {
    renderTabs();
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("marks the active tab selected and the other not", () => {
    renderTabs("rules");
    expect(rulesTab()).toHaveAttribute("aria-selected", "true");
    expect(recommendationsTab()).toHaveAttribute("aria-selected", "false");
  });

  it("points the panel at its tab and the tab at its panel", () => {
    renderTabs();
    const panel = screen.getByRole("tabpanel");
    expect(recommendationsTab()).toHaveAttribute(
      "aria-controls",
      panel.getAttribute("id"),
    );
    expect(panel).toHaveAttribute(
      "aria-labelledby",
      recommendationsTab().getAttribute("id"),
    );
  });

  it("keeps a single tab stop with a roving tabIndex", () => {
    renderTabs();
    expect(recommendationsTab()).toHaveAttribute("tabindex", "0");
    expect(rulesTab()).toHaveAttribute("tabindex", "-1");
  });

  it("has no accessibility violations", async () => {
    const { container } = renderTabs();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("PricingTabs — only the active panel is mounted (R2.1, R5.1)", () => {
  it("does not render the inactive panel's content at all", () => {
    // Not `hidden` by CSS: the inactive tab's query must not fire until someone
    // opens it, and a mounted-but-hidden panel would fire it on load.
    render(<Interactive />);
    expect(screen.getByText("contenido de recomendaciones")).toBeInTheDocument();
    expect(screen.queryByText("contenido de reglas")).not.toBeInTheDocument();
  });

  it("swaps the mounted content when the other tab is opened", () => {
    render(<Interactive />);
    fireEvent.click(rulesTab());
    expect(screen.getByText("contenido de reglas")).toBeInTheDocument();
    expect(
      screen.queryByText("contenido de recomendaciones"),
    ).not.toBeInTheDocument();
  });
});

describe("PricingTabs — keyboard (design D10)", () => {
  it("moves right and wraps to the first tab", () => {
    render(<Interactive />);
    fireEvent.keyDown(recommendationsTab(), { key: "ArrowRight" });
    expect(rulesTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(rulesTab(), { key: "ArrowRight" });
    expect(recommendationsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves left and wraps to the last tab", () => {
    render(<Interactive />);
    fireEvent.keyDown(recommendationsTab(), { key: "ArrowLeft" });
    expect(rulesTab()).toHaveAttribute("aria-selected", "true");
  });

  it("jumps to the first tab with Home and the last with End", () => {
    render(<Interactive />);
    fireEvent.keyDown(recommendationsTab(), { key: "End" });
    expect(rulesTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(rulesTab(), { key: "Home" });
    expect(recommendationsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves focus with the selection, so the tab stop is not stranded", () => {
    // Without this the roving tabIndex would leave focus on an element that is
    // no longer tabbable, and the next Tab press would jump out of the tablist.
    render(<Interactive />);
    fireEvent.keyDown(recommendationsTab(), { key: "ArrowRight" });
    expect(rulesTab()).toHaveFocus();
  });

  it("ignores keys the pattern does not define", () => {
    const { onTabChange } = renderTabs();
    for (const key of ["ArrowUp", "ArrowDown", "a", "Escape"]) {
      fireEvent.keyDown(recommendationsTab(), { key });
    }
    expect(onTabChange).not.toHaveBeenCalled();
  });

  it("selects on click", () => {
    const { onTabChange } = renderTabs();
    fireEvent.click(rulesTab());
    expect(onTabChange).toHaveBeenCalledWith("rules");
  });
});
