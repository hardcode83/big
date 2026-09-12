import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import { ReviewsTabs, type ReviewsTabKey } from "./reviews-tabs";

const PANELS = {
  drafts: { key: "drafts-panel", node: <p>contenido de borradores</p> },
  reviews: { key: "reviews-panel", node: <p>contenido de reseñas</p> },
};

function renderTabs(activeTab: ReviewsTabKey = "drafts") {
  const onTabChange = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <ReviewsTabs activeTab={activeTab} onTabChange={onTabChange} panels={PANELS} />
    </I18nProvider>,
  );
  return { ...result, onTabChange };
}

function Interactive() {
  const [tab, setTab] = useState<ReviewsTabKey>("drafts");
  return (
    <I18nProvider locale="es">
      <ReviewsTabs activeTab={tab} onTabChange={setTab} panels={PANELS} />
    </I18nProvider>
  );
}

const draftsTab = () => screen.getByRole("tab", { name: "Borradores" });
const reviewsTab = () => screen.getByRole("tab", { name: "Reseñas" });

describe("ReviewsTabs — structure (R1.1, design D13)", () => {
  it("exposes a tablist with two tabs and one panel", () => {
    renderTabs();
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("marks the active tab selected and the other not", () => {
    renderTabs("reviews");
    expect(reviewsTab()).toHaveAttribute("aria-selected", "true");
    expect(draftsTab()).toHaveAttribute("aria-selected", "false");
  });

  it("points the panel at its tab and the tab at its panel", () => {
    renderTabs();
    const panel = screen.getByRole("tabpanel");
    expect(draftsTab()).toHaveAttribute(
      "aria-controls",
      panel.getAttribute("id"),
    );
    expect(panel).toHaveAttribute(
      "aria-labelledby",
      draftsTab().getAttribute("id"),
    );
  });

  it("keeps a single tab stop with a roving tabIndex", () => {
    renderTabs();
    expect(draftsTab()).toHaveAttribute("tabindex", "0");
    expect(reviewsTab()).toHaveAttribute("tabindex", "-1");
  });

  it("has no accessibility violations", async () => {
    const { container } = renderTabs();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("ReviewsTabs — only the active panel is mounted (R2.1, R5.1)", () => {
  it("does not render the inactive panel's content at all", () => {
    render(<Interactive />);
    expect(screen.getByText("contenido de borradores")).toBeInTheDocument();
    expect(screen.queryByText("contenido de reseñas")).not.toBeInTheDocument();
  });

  it("swaps the mounted content when the other tab is opened", () => {
    render(<Interactive />);
    fireEvent.click(reviewsTab());
    expect(screen.getByText("contenido de reseñas")).toBeInTheDocument();
    expect(
      screen.queryByText("contenido de borradores"),
    ).not.toBeInTheDocument();
  });
});

describe("ReviewsTabs — keyboard (design D13)", () => {
  it("moves right and wraps to the first tab", () => {
    render(<Interactive />);
    fireEvent.keyDown(draftsTab(), { key: "ArrowRight" });
    expect(reviewsTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(reviewsTab(), { key: "ArrowRight" });
    expect(draftsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves left and wraps to the last tab", () => {
    render(<Interactive />);
    fireEvent.keyDown(draftsTab(), { key: "ArrowLeft" });
    expect(reviewsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("jumps to the first tab with Home and the last with End", () => {
    render(<Interactive />);
    fireEvent.keyDown(draftsTab(), { key: "End" });
    expect(reviewsTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(reviewsTab(), { key: "Home" });
    expect(draftsTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves focus with the selection, so the tab stop is not stranded", () => {
    render(<Interactive />);
    fireEvent.keyDown(draftsTab(), { key: "ArrowRight" });
    expect(reviewsTab()).toHaveFocus();
  });

  it("ignores keys the pattern does not define", () => {
    const { onTabChange } = renderTabs();
    for (const key of ["ArrowUp", "ArrowDown", "a", "Escape"]) {
      fireEvent.keyDown(draftsTab(), { key });
    }
    expect(onTabChange).not.toHaveBeenCalled();
  });

  it("selects on click", () => {
    const { onTabChange } = renderTabs();
    fireEvent.click(reviewsTab());
    expect(onTabChange).toHaveBeenCalledWith("reviews");
  });
});
