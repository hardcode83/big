import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type HeadingTag = "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

/**
 * Shared layout primitive for the cross-cutting states (design D8). It only owns
 * layout, spacing, and iconography; each state (loading/error/empty/planned)
 * composes it but keeps its own semantics and API. No "use client": renderable
 * in Server Components.
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
    <section
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
      <Heading className="text-lg font-semibold text-foreground">{title}</Heading>
      {description ? (
        <p className="max-w-prose text-sm text-muted-foreground">{description}</p>
      ) : null}
      {children}
    </section>
  );
}
