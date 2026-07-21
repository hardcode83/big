import type { ReactNode } from "react";

/**
 * Optional in-content header with a contextual slot for a feature's tabs or
 * actions (design D5). The slot stays empty for placeholders in this change;
 * presentational and server-compatible.
 */
export function PageHeader({
  title,
  actions,
}: {
  title?: ReactNode;
  actions?: ReactNode;
}) {
  if (!title && !actions) {
    return null;
  }
  return (
    <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
      <div className="min-w-0">{title}</div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}
