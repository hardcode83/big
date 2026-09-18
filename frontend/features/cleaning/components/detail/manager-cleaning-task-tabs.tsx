"use client";

import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * The two tabs of the manager's cleaning task detail screen: **Tarea** (the
 * operational content, active by default — R2.1) and **Mensajes** (design D4).
 *
 * Hand-rolled for the same reason `CleanerTaskTabs` and `TechIncidentTabs`
 * are: there is no `Tabs` primitive in `components/ui/`, and adding one means
 * a fresh dependency plus a reinstall across every worktree's
 * `frontend_node_modules` volume. Same ARIA contract as those two —
 * `role="tablist"` / `role="tab"` (`aria-selected`, `aria-controls`, roving
 * `tabIndex`) / `role="tabpanel"` (`aria-labelledby`), ←/→ to move, Home/End
 * to jump.
 *
 * **Both panels stay mounted** and the inactive one is hidden with the `hidden`
 * HTML attribute: R2.1 requires the content tab's scroll and form state (the
 * cancel confirmation, the live region) to survive a round trip through the
 * messages tab. `hidden` also takes the inactive panel out of the
 * accessibility tree and out of the tab order, so the keyboard user never
 * lands inside a panel that is not on screen.
 *
 * The messages query stays lazy all the same: `hasOpenedMessagesTab` flips to
 * `true` the first time the Messages tab is selected and never goes back, and
 * `renderMessages` receives it as `enabled` — nothing is requested before the
 * manager asks for the thread (R2.1), and alternating tabs afterwards does
 * not take it away again (D4).
 */

export type ManagerCleaningTaskTabKey = "content" | "messages";

const TAB_ORDER: readonly ManagerCleaningTaskTabKey[] = ["content", "messages"];

const PANEL_IDS: Record<ManagerCleaningTaskTabKey, string> = {
  content: "manager-cleaning-panel-content",
  messages: "manager-cleaning-panel-messages",
};

export interface ManagerCleaningTaskTabsProps {
  /** The operational content of the task — the default tab (R2.1). */
  content: ReactNode;
  /**
   * Rendered with the sticky "the messages tab has been opened" flag, which
   * the messages panel passes straight to its query's `enabled` (D4).
   */
  renderMessages: (enabled: boolean) => ReactNode;
}

export function ManagerCleaningTaskTabs({
  content,
  renderMessages,
}: ManagerCleaningTaskTabsProps) {
  const { t } = useTranslation("cleaning");
  const [activeTab, setActiveTab] = useState<ManagerCleaningTaskTabKey>("content");
  const [hasOpenedMessagesTab, setHasOpenedMessagesTab] = useState(false);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function selectTab(key: ManagerCleaningTaskTabKey) {
    setActiveTab(key);
    // Sticky: once true it never returns to false, so the thread is not
    // re-disabled when the manager goes back to the content tab (D4).
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

  const panels: Record<ManagerCleaningTaskTabKey, ReactNode> = {
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
              id={`manager-cleaning-tab-${key}`}
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
          aria-labelledby={`manager-cleaning-tab-${key}`}
          tabIndex={key === activeTab ? 0 : -1}
          hidden={key !== activeTab}
        >
          {panels[key]}
        </div>
      ))}
    </div>
  );
}
