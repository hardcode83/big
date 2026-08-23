"use client";

import { useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import type { PricingTab } from "../state/use-pricing-ui-store";

/**
 * The two tabs of `/pricing`, hand-built against the ARIA tabs pattern (design
 * D10). There is no `Tabs` primitive in `components/ui/` and no `@radix-ui`
 * tabs package in the tree; resolving this with the platform is the same posture
 * the tree already took for `<select>` in `cleaning-filters.tsx`, and the cost of
 * the alternative is not only the package — `node_modules` lives in a Docker
 * volume, so a new dependency means reinstalling in every live worktree's stack.
 *
 * **Only the active panel is mounted** (conditional render, not `hidden` by CSS),
 * so the inactive tab's query does not fire until someone opens it (R2.1, R5.1).
 * Coming back, TanStack Query serves it from cache without a request.
 *
 * Keyboard: roving `tabIndex` (only the selected tab is tabbable), left/right to
 * move, Home/End to jump. Activation follows selection, which is the pattern's
 * default for cheap panels.
 */
export interface PricingTabsProps {
  activeTab: PricingTab;
  onTabChange: (tab: PricingTab) => void;
  /** Rendered inside the single `tabpanel`; only the active one is built. */
  children: ReactNode;
}

const TABS: readonly PricingTab[] = ["recommendations", "rules"];

export function PricingTabs({
  activeTab,
  onTabChange,
  children,
}: PricingTabsProps) {
  const { t } = useTranslation("pricing");
  const refs = useRef<Partial<Record<PricingTab, HTMLButtonElement | null>>>({});

  function focusTab(tab: PricingTab) {
    onTabChange(tab);
    // The newly selected tab becomes the tabbable one, so focus has to follow
    // it or the user's next Tab press would leave the tablist entirely.
    refs.current[tab]?.focus();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    const index = TABS.indexOf(activeTab);
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        focusTab(TABS[(index + 1) % TABS.length]);
        break;
      case "ArrowLeft":
        event.preventDefault();
        focusTab(TABS[(index - 1 + TABS.length) % TABS.length]);
        break;
      case "Home":
        event.preventDefault();
        focusTab(TABS[0]);
        break;
      case "End":
        event.preventDefault();
        focusTab(TABS[TABS.length - 1]);
        break;
      default:
        break;
    }
  }

  return (
    <div className="flex min-w-0 flex-col">
      <div
        role="tablist"
        aria-label={t("tabs.label")}
        className="flex gap-1 border-b px-4"
      >
        {TABS.map((tab) => {
          const selected = tab === activeTab;
          return (
            <button
              key={tab}
              ref={(node) => {
                refs.current[tab] = node;
              }}
              type="button"
              role="tab"
              id={`pricing-tab-${tab}`}
              aria-selected={selected}
              aria-controls={`pricing-panel-${tab}`}
              // Roving tabIndex: one stop for the whole tablist.
              tabIndex={selected ? 0 : -1}
              onClick={() => onTabChange(tab)}
              onKeyDown={onKeyDown}
              className={cn(
                "tap-target -mb-px border-b-2 px-3 py-2 text-sm font-medium",
                selected
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`tabs.${tab}`)}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`pricing-panel-${activeTab}`}
        aria-labelledby={`pricing-tab-${activeTab}`}
        tabIndex={0}
      >
        {children}
      </div>
    </div>
  );
}
