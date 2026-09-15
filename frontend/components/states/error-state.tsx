import type { ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatePanel } from "./state-panel";

/**
 * Error convention (design D8): an `alert` region. Retry is offered ONLY when a
 * real reset callback is supplied — never a fake button. The message is provided
 * (localized) by the caller; this component never renders raw error details.
 *
 * The retry control is the user's only escape from the error state, so it gets
 * the shared `tap-target` utility (steering/frontend.md: Interaction targets —
 * 44x44 CSS px minimum) instead of the default Button height, and an explicit
 * `focus-visible` is preserved through the underlying shadcn Button.
 */
export interface ErrorStateProps {
  title: ReactNode;
  description?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

export function ErrorState({
  title,
  description,
  onRetry,
  retryLabel,
  className,
}: ErrorStateProps) {
  return (
    <StatePanel
      role="alert"
      className={className}
      icon={<TriangleAlert className="size-8" />}
      title={title}
      description={description}
    >
      {onRetry && retryLabel ? (
        <Button
          type="button"
          variant="outline"
          onClick={onRetry}
          className="tap-target"
        >
          {retryLabel}
        </Button>
      ) : null}
    </StatePanel>
  );
}
