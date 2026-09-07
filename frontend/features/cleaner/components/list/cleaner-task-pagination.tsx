"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * Presentational page navigation for the cleaner's list (R1.4).
 *
 * Same shape as `cleaning-pagination.tsx`: prev/next + "página X de Y".
 * `page`, `totalPages` and `total` come from the response envelope the
 * backend returned, and moving is `onPageChange`'s business.
 */
export interface CleanerTaskPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function CleanerTaskPagination({
  page,
  totalPages,
  total,
  onPageChange,
}: CleanerTaskPaginationProps) {
  const { t } = useTranslation("cleaner");
  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <nav
      aria-label={t("pagination.label")}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3"
    >
      <p className="text-body-base text-muted-foreground">
        {t("pagination.pageOfTotal", { page, totalPages })}{" "}
        {t("pagination.totalTasks", { total })}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={isFirst}
          onClick={() => onPageChange(page - 1)}
        >
          {t("pagination.previous")}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={isLast}
          onClick={() => onPageChange(page + 1)}
        >
          {t("pagination.next")}
        </Button>
      </div>
    </nav>
  );
}