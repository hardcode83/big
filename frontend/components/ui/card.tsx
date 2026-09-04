import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * The shadcn-shaped `Card` primitive (design D2): the one place that owns
 * `bg-surface`, `border`, `rounded-xl`, `shadow-sm` and the hover-revealed
 * gradient top border (`card-hover-gradient`, design D4 / `app/globals.css`).
 * Every ad-hoc `rounded-lg border bg-surface p-4 shadow-sm` div across the
 * dashboard/properties/cleaning/cleaner/pricing screens migrates onto this in
 * later sections instead of restating these classes per screen.
 *
 * No `variant` axis: unlike `Badge`/`Button`, nothing in scope needs a second
 * visual treatment for a card, so `cardVariants` carries only the base recipe.
 * The `cva` wrapper is kept anyway to mirror the shape of `badgeVariants`.
 */
const cardVariants = cva(
  "relative rounded-xl border bg-surface shadow-sm card-hover-gradient",
);

export interface CardProps
  extends React.ComponentProps<"div">,
    VariantProps<typeof cardVariants> {}

function Card({ className, ...props }: CardProps) {
  return (
    <div
      data-slot="card"
      className={cn(cardVariants(), className)}
      {...props}
    />
  );
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn("flex flex-col gap-1.5 p-6", className)}
      {...props}
    />
  );
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("p-6 pt-0", className)}
      {...props}
    />
  );
}

export { Card, CardHeader, CardContent, cardVariants };
