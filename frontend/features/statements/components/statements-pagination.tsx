"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * Presentational page navigation for the statements list (R2.4).
 *
 * `OwnerStatementPageResponse` publishes only `items`, `total`, `page` and
 * `per_page` — `total_pages` is deliberately not part of the contract (see
 * `data/dto.ts`). This component derives a display-only page count from
 * `total`/`perPage` purely to render "page X of Y" and to decide whether
 * "previous"/"next" are enabled; that derived number is never stored, never
 * sent back to the server, and never treated as part of the DTO — it exists
 * only for this render.
 *
 * Same shape as `features/reviews/components/reviews-pagination.tsx` and
 * `features/pricing/components/pricing-pagination.tsx`: no page-size
 * selector (`per_page` is the backend default), and rendering nothing when
 * there is nothing to page through.
 */
export interface StatementsPaginationProps {
  page: number;
  total: number;
  perPage: number;
  onPageChange: (page: number) => void;
}

export function StatementsPagination({
  page,
  total,
  perPage,
  onPageChange,
}: StatementsPaginationProps) {
  const { t } = useTranslation("statements");

  // total=0 is the empty-list case (R2.4); the panel renders EmptyState
  // instead, so there is nothing to navigate here.
  const totalPages = total > 0 && perPage > 0 ? Math.ceil(total / perPage) : 0;
  if (totalPages <= 0) {
    return null;
  }

  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <nav
      aria-label={t("pagination.label")}
      className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3"
    >
      <p className="min-w-0 break-words text-body-base text-muted-foreground">
        {t("pagination.pageOfTotal", { page, totalPages })} {t("separator")}{" "}
        {t("pagination.totalItems", { total })}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          className="tap-target"
          disabled={isFirst}
          onClick={() => onPageChange(page - 1)}
        >
          {t("pagination.previous")}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="tap-target"
          disabled={isLast}
          onClick={() => onPageChange(page + 1)}
        >
          {t("pagination.next")}
        </Button>
      </div>
    </nav>
  );
}
