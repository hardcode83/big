import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { StatePanel } from "./state-panel";

/**
 * Planned-module convention (design D8). NOT a bare "Coming Soon" string: a
 * neutral informative panel with a planned badge, localized title/description
 * (from the route registry), and a localized explanation. It has NO alert role,
 * NO retry, and NO business data/actions/ETA/progress, so it is never confused
 * with an error or an empty result. Presentational and server-compatible; all
 * text arrives already localized as props — a dynamic route's param is never
 * rendered here.
 */
export interface ModulePlaceholderProps {
  icon?: ReactNode;
  badgeLabel: string;
  title: ReactNode;
  description?: ReactNode;
  explanation: ReactNode;
  className?: string;
}

export function ModulePlaceholder({
  icon,
  badgeLabel,
  title,
  description,
  explanation,
  className,
}: ModulePlaceholderProps) {
  return (
    <StatePanel
      className={className}
      icon={icon}
      title={title}
      description={description}
    >
      <Badge variant="secondary">{badgeLabel}</Badge>
      <p className="max-w-prose text-sm text-muted-foreground">{explanation}</p>
    </StatePanel>
  );
}
