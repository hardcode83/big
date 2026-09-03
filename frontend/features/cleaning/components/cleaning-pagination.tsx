"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * Presentational page navigation for the cleaning list (design D13, R1.5). It owns
 * no state: `page`, `totalPages` and `total` come from the response envelope the
 * backend returned, and moving is `onPageChange`'s business.
 *
 * Prev/next rather than a numbered list, and no infinite scroll: R1.5 asks for
 * `total`/`total_pages` to be reflected, which "página X de Y" does and an endless
 * list does not.
 */
export interface CleaningPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function CleaningPagination({
  page,
  totalPages,
  total,
  onPageChange,
}: CleaningPaginationProps) {
  const { t } = useTranslation("cleaning");
  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <nav
      aria-label={t("pagination.label")}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3"
    >
      <p className="text-body-base text-muted-foreground">
        {t("pagination.pageOfTotal", { page, totalPages })}{" "}
        {t("separator")} {t("pagination.totalTasks", { total })}
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
