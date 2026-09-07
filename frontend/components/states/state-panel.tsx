import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type HeadingTag = "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

/**
 * Shared layout primitive for the cross-cutting states (design D8). It only owns
 * layout, spacing, and iconography; each state (loading/error/empty/planned)
 * composes it but keeps its own semantics and API. No "use client": renderable
 * in Server Components.
 *
 * Sits on the Tier-1 `Card` (visual-restyle-workspace R2/D6) so every loading,
 * error, empty and planned-module surface shares the same `bg-surface`/border/
 * shadow/hover-gradient treatment instead of a bare `<section>`. `Card` forwards
 * `role`/`aria-*` straight to its root `div`, so the alert/status semantics each
 * state relies on are unaffected by swapping the element.
 */
export interface StatePanelProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  className?: string;
  /** Landmark role, e.g. "alert" for errors or "status" for loading. */
  role?: string;
  headingLevel?: 1 | 2 | 3 | 4 | 5 | 6;
  "aria-busy"?: boolean;
  "aria-live"?: "polite" | "assertive" | "off";
}

export function StatePanel({
  icon,
  title,
  description,
  children,
  className,
  role,
  headingLevel = 2,
  ...aria
}: StatePanelProps) {
  const Heading: HeadingTag = `h${headingLevel}`;
  return (
    <Card
      role={role}
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-12 text-center",
        className,
      )}
      {...aria}
    >
      {icon ? (
        <div className="text-muted-foreground" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <Heading className="text-headline-md font-semibold text-foreground">
        {title}
      </Heading>
      {description ? (
        <p className="max-w-prose text-body-base text-muted-foreground">
          {description}
        </p>
      ) : null}
      {children}
    </Card>
  );
}
