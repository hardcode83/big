import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

import { StatePanel } from "./state-panel";

/**
 * Empty convention (design D8): a neutral region for a valid operation that
 * returned no items. No alert and no busy semantics — distinct from Error and
 * Loading. An optional action may be supplied by a real feature (never a
 * business mock in this change).
 */
export interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <StatePanel
      className={className}
      icon={<Inbox className="size-8" />}
      title={title}
      description={description}
    >
      {action}
    </StatePanel>
  );
}
