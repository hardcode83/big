import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "./state-panel";

/**
 * Loading convention (design D8): a non-intrusive `status` region marked
 * `aria-busy` with skeleton content. The visible label is provided (localized)
 * by the caller. Distinct from Error (no alert) and Empty (an operation is
 * pending, not finished).
 */
export interface LoadingStateProps {
  label: string;
  className?: string;
}

export function LoadingState({ label, className }: LoadingStateProps) {
  return (
    <StatePanel
      role="status"
      aria-busy
      aria-live="polite"
      className={className}
      title={<span className="sr-only">{label}</span>}
    >
      <div className="w-full max-w-sm space-y-3" aria-hidden="true">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </StatePanel>
  );
}
