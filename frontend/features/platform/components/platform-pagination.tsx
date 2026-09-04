"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * Presentational page navigation for the tenant list (design D10). A third
 * near-copy of `CleaningPagination`/`PricingPagination`, hardcoding the
 * `"platform"` i18n namespace exactly as the other two hardcode theirs — the
 * user chose to keep this change scoped to its own files instead of also
 * touching `features/cleaning` and `features/pricing` to extract a shared,
 * namespace-parameterized component. It owns no state: `page`, `totalPages`
 * and `total` come from the response envelope the backend returned, and
 * moving is `onPageChange`'s business.
 */
export interface PlatformPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function PlatformPagination({
  page,
  totalPages,
  total,
  onPageChange,
}: PlatformPaginationProps) {
  const { t } = useTranslation("platform");
  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <nav
      aria-label={t("pagination.label")}
      className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3"
    >
      <p className="text-sm text-muted-foreground">
        {t("pagination.pageOfTotal", { page, totalPages })}{" "}
        {t("pagination.totalItems", { total })}
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
