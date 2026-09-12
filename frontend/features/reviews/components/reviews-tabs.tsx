"use client";

import { useRef, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

/**
 * Tablist with two tabs: **Borradores** (default) and **Reseñas** (design D13).
 *
 * Rendered by hand (no Radix Tabs) for the same reason pricing-web D10
 * rejected it: no `Tabs` primitive in `components/ui/`, and adding one would
 * mean a fresh dependency plus a reinstall across every worktree's
 * `frontend_node_modules` volume.
 *
 * - `role="tablist"` on the wrapper, `role="tab"` on each button (`aria-selected`,
 *   `aria-controls`, roving `tabIndex`), `role="tabpanel"` with `aria-labelledby`
 *   on the single mounted panel.
 * - Keyboard: ←/→ move focus between tabs, Home/End jump to first/last.
 *   The focus stays on the tablist; the active panel takes focus when its tab
 *   is activated (the standard ARIA pattern).
 * - Only the **active** panel is mounted: the panel hook never fires until
 *   the tab is opened (R2.1, R5.1), and TanStack Query serves the cached
 *   results on the way back.
 *
 * The `panels` prop is a record — not an array — because the active key is
 * the same string the view already stores in the UI store, and `Record<Tab, …>`
 * makes the second tab a compile-time obligation, not a runtime invariant
 * that only the test catches.
 */

export type ReviewsTabKey = "drafts" | "reviews";

export interface ReviewsTabsProps<Tab extends string> {
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  panels: Record<Tab, { key: string; node: React.ReactNode }>;
}

export function ReviewsTabs<Tab extends string>({
  activeTab,
  onTabChange,
  panels,
}: ReviewsTabsProps<Tab>) {
  const { t } = useTranslation("reviews");
  const tabsOrder = Object.keys(panels) as Tab[];
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function handleKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (
      event.key === "ArrowRight" ||
      event.key === "ArrowLeft" ||
      event.key === "Home" ||
      event.key === "End"
    ) {
      event.preventDefault();
      let nextIndex = index;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % tabsOrder.length;
      if (event.key === "ArrowLeft")
        nextIndex = (index - 1 + tabsOrder.length) % tabsOrder.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabsOrder.length - 1;
      const nextKey = tabsOrder[nextIndex];
      if (nextKey !== undefined) {
        onTabChange(nextKey);
        tabRefs.current[nextKey]?.focus();
      }
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        role="tablist"
        aria-label={t("tabs.label")}
        className="flex border-b border-border"
      >
        {tabsOrder.map((key, index) => {
          const selected = key === activeTab;
          const panelKey = panels[key].key;
          return (
            <button
              key={key}
              ref={(el) => {
                tabRefs.current[key] = el;
              }}
              type="button"
              role="tab"
              id={`reviews-tab-${key}`}
              aria-selected={selected}
              aria-controls={panelKey}
              tabIndex={selected ? 0 : -1}
              onClick={() => onTabChange(key)}
              onKeyDown={(event) => handleKey(event, index)}
              className={`px-4 py-2 text-body-base font-medium ${
                selected
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground"
              }`}
            >
              {t(`tabs.${key}`)}
            </button>
          );
        })}
      </div>
      {tabsOrder.map((key) => {
        const panel = panels[key];
        if (key !== activeTab) return null;
        return (
          <div
            key={key}
            role="tabpanel"
            id={panel.key}
            aria-labelledby={`reviews-tab-${key}`}
            tabIndex={0}
          >
            {panel.node}
          </div>
        );
      })}
    </div>
  );
}