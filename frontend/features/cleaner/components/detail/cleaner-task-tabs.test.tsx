import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import { CleanerTaskTabs } from "./cleaner-task-tabs";

/**
 * A stateful child of the **content** tab, standing in for
 * `CleanerIncidentReportPanel` (whose `open`/`title`/`description` state R3.2
 * protects): if the tabs unmounted the inactive panel, the count would be back
 * at 0 after a round trip through the messages tab.
 */
function Counter() {
  const [count, setCount] = useState(0);
  return (
    <button type="button" onClick={() => setCount((value) => value + 1)}>
      contador: {count}
    </button>
  );
}

function renderTabs(renderMessages = (enabled: boolean) => (
  <p>mensajes habilitados: {String(enabled)}</p>
)) {
  return render(
    <I18nProvider locale="es">
      <CleanerTaskTabs
        content={
          <div>
            <p>contenido operacional</p>
            <Counter />
          </div>
        }
        renderMessages={renderMessages}
      />
    </I18nProvider>,
  );
}

const contentTab = () => screen.getByRole("tab", { name: "Tarea" });
const messagesTab = () => screen.getByRole("tab", { name: "Mensajes" });

describe("CleanerTaskTabs — structure and defaults (R3.1)", () => {
  it("exposes a tablist with both tabs and both panels", () => {
    renderTabs();
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    // `hidden` hides the inactive panel from the accessibility tree, so only
    // the active one is queryable by role — both are in the DOM (see below).
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("opens on the operational content tab, not on messages (R3.1)", () => {
    renderTabs();
    expect(contentTab()).toHaveAttribute("aria-selected", "true");
    expect(messagesTab()).toHaveAttribute("aria-selected", "false");
    expect(screen.getByText("contenido operacional")).toBeVisible();
  });

  it("points each tab at its panel and back", () => {
    renderTabs();
    const panel = screen.getByRole("tabpanel");
    expect(contentTab()).toHaveAttribute(
      "aria-controls",
      panel.getAttribute("id"),
    );
    expect(panel).toHaveAttribute(
      "aria-labelledby",
      contentTab().getAttribute("id"),
    );
  });

  it("keeps a single tab stop with a roving tabIndex", () => {
    renderTabs();
    expect(contentTab()).toHaveAttribute("tabindex", "0");
    expect(messagesTab()).toHaveAttribute("tabindex", "-1");
  });

  it("has no accessibility violations", async () => {
    const { container } = renderTabs();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("CleanerTaskTabs — both panels stay mounted (R3.2, design D1)", () => {
  it("keeps the inactive panel in the DOM, hidden rather than unmounted", () => {
    renderTabs();
    const messagesPanel = document.getElementById(
      "cleaner-task-panel-messages",
    );
    expect(messagesPanel).not.toBeNull();
    expect(messagesPanel).toHaveAttribute("hidden");
    expect(messagesPanel).not.toBeVisible();

    fireEvent.click(messagesTab());
    expect(document.getElementById("cleaner-task-panel-content")).toHaveAttribute(
      "hidden",
    );
    expect(document.getElementById("cleaner-task-panel-messages")).not.toHaveAttribute(
      "hidden",
    );
  });

  it("preserves the content panel's local state across a round trip to messages (R3.2)", () => {
    renderTabs();
    const counter = screen.getByRole("button", { name: "contador: 0" });
    fireEvent.click(counter);
    fireEvent.click(screen.getByRole("button", { name: "contador: 1" }));
    expect(
      screen.getByRole("button", { name: "contador: 2" }),
    ).toBeInTheDocument();

    fireEvent.click(messagesTab());
    fireEvent.click(contentTab());

    // Had the panel been unmounted (the `reviews-tabs.tsx` behaviour this
    // component deliberately diverges from), this would read "contador: 0".
    expect(
      screen.getByRole("button", { name: "contador: 2" }),
    ).toBeInTheDocument();
  });

  it("does not remount the content panel when the other tab is opened", () => {
    const mounted = vi.fn();
    function Probe() {
      useState(() => {
        mounted();
        return null;
      });
      return <p>sonda</p>;
    }
    render(
      <I18nProvider locale="es">
        <CleanerTaskTabs
          content={<Probe />}
          renderMessages={() => <p>mensajes</p>}
        />
      </I18nProvider>,
    );
    expect(mounted).toHaveBeenCalledTimes(1);
    fireEvent.click(messagesTab());
    fireEvent.click(contentTab());
    expect(mounted).toHaveBeenCalledTimes(1);
  });
});

describe("CleanerTaskTabs — lazy, sticky messages flag (design D1)", () => {
  it("renders the messages panel disabled until its tab is opened", () => {
    const renderMessages = vi.fn((enabled: boolean) => (
      <p>mensajes habilitados: {String(enabled)}</p>
    ));
    renderTabs(renderMessages);
    expect(renderMessages).toHaveBeenLastCalledWith(false);

    fireEvent.click(messagesTab());
    expect(renderMessages).toHaveBeenLastCalledWith(true);
  });

  it("never flips the flag back when the cleaner returns to the content tab", () => {
    const renderMessages = vi.fn((enabled: boolean) => (
      <p>mensajes habilitados: {String(enabled)}</p>
    ));
    renderTabs(renderMessages);
    fireEvent.click(messagesTab());
    fireEvent.click(contentTab());
    expect(renderMessages).toHaveBeenLastCalledWith(true);
  });
});

describe("CleanerTaskTabs — keyboard (R4.4)", () => {
  it("moves right and wraps around", () => {
    renderTabs();
    fireEvent.keyDown(contentTab(), { key: "ArrowRight" });
    expect(messagesTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(messagesTab(), { key: "ArrowRight" });
    expect(contentTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves left and wraps to the last tab", () => {
    renderTabs();
    fireEvent.keyDown(contentTab(), { key: "ArrowLeft" });
    expect(messagesTab()).toHaveAttribute("aria-selected", "true");
  });

  it("jumps to the first tab with Home and the last with End", () => {
    renderTabs();
    fireEvent.keyDown(contentTab(), { key: "End" });
    expect(messagesTab()).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(messagesTab(), { key: "Home" });
    expect(contentTab()).toHaveAttribute("aria-selected", "true");
  });

  it("moves focus with the selection, so the tab stop is not stranded", () => {
    renderTabs();
    fireEvent.keyDown(contentTab(), { key: "ArrowRight" });
    expect(messagesTab()).toHaveFocus();
  });

  it("enables the messages query when the tab is reached by keyboard too", () => {
    const renderMessages = vi.fn((enabled: boolean) => (
      <p>mensajes habilitados: {String(enabled)}</p>
    ));
    renderTabs(renderMessages);
    fireEvent.keyDown(contentTab(), { key: "End" });
    expect(renderMessages).toHaveBeenLastCalledWith(true);
  });

  it("ignores keys the pattern does not define", () => {
    renderTabs();
    for (const key of ["ArrowUp", "ArrowDown", "a", "Escape"]) {
      fireEvent.keyDown(contentTab(), { key });
    }
    expect(contentTab()).toHaveAttribute("aria-selected", "true");
  });
});
