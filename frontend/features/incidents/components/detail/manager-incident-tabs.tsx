"use client";

import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * The two tabs of the manager's incident detail screen: **Incidencia** (the
 * operational content, active by default — R1.1) and **Mensajes** (design
 * D3, D-mobile).
 *
 * Hand-rolled for the same reason `tech-incident-tabs.tsx` is: there is no
 * `Tabs` primitive in `components/ui/`, and adding one means a fresh
 * dependency plus a reinstall across every worktree's
 * `frontend_node_modules` volume. Same ARIA contract as that component —
 * `role="tablist"` / `role="tab"` (`aria-selected`, `aria-controls`, roving
 * `tabIndex`) / `role="tabpanel"` (`aria-labelledby`), ←/→ to move, Home/End
 * to jump.
 *
 * **Both panels stay mounted**, the inactive one is hidden with the `hidden`
 * HTML attribute: R1.1 requires the content tab's scroll and form state
 * (`ManagerIncidentActions`' sheet state) to survive a round trip through
 * the messages tab. `hidden` takes the inactive panel out of the
 * accessibility tree and out of the tab order, so the keyboard user never
 * lands inside a panel that is not on screen.
 *
 * The messages query stays lazy all the same: `hasOpenedMessagesTab` flips
 * to `true` the first time the Messages tab is selected and never goes
 * back, and `renderMessages` receives it as `enabled` — nothing is
 * requested before the manager asks for the thread (R1.1), and alternating
 * tabs afterwards does not take it away again (D3).
 *
 * DOM IDs are prefixed `manager-incident-` to avoid collision with the
 * tech/cleaner tabs that share the same shape.
 */
export type ManagerIncidentTabKey = "content" | "messages";

const TAB_ORDER: readonly ManagerIncidentTabKey[] = ["content", "messages"];

const PANEL_IDS: Record<ManagerIncidentTabKey, string> = {
  content: "manager-incident-panel-content",
  messages: "manager-incident-panel-messages",
};

export interface ManagerIncidentTabsProps {
  /** The operational content of the incident — the default tab (R1.1). */
  content: ReactNode;
  /**
   * Rendered with the sticky "the messages tab has been opened" flag, which
   * the messages panel passes straight to its query's `enabled` (D3).
   */
  renderMessages: (enabled: boolean) => ReactNode;
}

export function ManagerIncidentTabs({
  content,
  renderMessages,
}: ManagerIncidentTabsProps) {
  const { t } = useTranslation("incidents");
  const [activeTab, setActiveTab] = useState<ManagerIncidentTabKey>("content");
  const [hasOpenedMessagesTab, setHasOpenedMessagesTab] = useState(false);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function selectTab(key: ManagerIncidentTabKey) {
    setActiveTab(key);
    // Sticky: once true it never returns to false, so the thread is not
    // re-disabled when the manager goes back to the content tab (D3).
    if (key === "messages") setHasOpenedMessagesTab(true);
  }

  function handleKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (
      event.key !== "ArrowRight" &&
      event.key !== "ArrowLeft" &&
      event.key !== "Home" &&
      event.key !== "End"
    ) {
      return;
    }
    event.preventDefault();
    let nextIndex = index;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % TAB_ORDER.length;
    if (event.key === "ArrowLeft")
      nextIndex = (index - 1 + TAB_ORDER.length) % TAB_ORDER.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = TAB_ORDER.length - 1;
    const nextKey = TAB_ORDER[nextIndex];
    if (nextKey !== undefined) {
      selectTab(nextKey);
      tabRefs.current[nextKey]?.focus();
    }
  }

  const panels: Record<ManagerIncidentTabKey, ReactNode> = {
    content,
    messages: renderMessages(hasOpenedMessagesTab),
  };

  return (
    <div className="flex flex-col gap-4">
      <div
        role="tablist"
        aria-label={t("tabs.label")}
        className="flex border-b border-border"
      >
        {TAB_ORDER.map((key, index) => {
          const selected = key === activeTab;
          return (
            <button
              key={key}
              ref={(el) => {
                tabRefs.current[key] = el;
              }}
              type="button"
              role="tab"
              id={`manager-incident-tab-${key}`}
              aria-selected={selected}
              aria-controls={PANEL_IDS[key]}
              tabIndex={selected ? 0 : -1}
              onClick={() => selectTab(key)}
              onKeyDown={(event) => handleKey(event, index)}
              className={`tap-target flex-1 px-4 py-2 text-body-base font-medium ${
                selected
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {key === "messages" ? t("messages.tab") : t("tabs.content")}
            </button>
          );
        })}
      </div>
      {TAB_ORDER.map((key) => (
        <div
          key={key}
          role="tabpanel"
          id={PANEL_IDS[key]}
          aria-labelledby={`manager-incident-tab-${key}`}
          tabIndex={key === activeTab ? 0 : -1}
          hidden={key !== activeTab}
        >
          {panels[key]}
        </div>
      ))}
    </div>
  );
}
