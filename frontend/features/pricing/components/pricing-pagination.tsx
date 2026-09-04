"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * Presentational page navigation for both pricing tabs (design D18). It owns no
 * state: `page`, `totalPages` and `total` come from the normalized envelope, and
 * moving is `onPageChange`'s business. It never touches the network.
 *
 * Not `CleaningPagination` reused: that component calls
 * `useTranslation("cleaning")` in its body, so its texts would come from the
 * wrong catalog. A single component parameterized by namespace is the extraction
 * the tree reserves for the third consumer; this is the second.
 *
 * No page-size selector — `per_page` is fixed at the backend's default of 20 and
 * no requirement asks for one.
 */
export interface PricingPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
  /** Overrides the `aria-label`, so the two tabs do not announce the same nav. */
  labelKey?: string;
}

export function PricingPagination({
  page,
  totalPages,
  total,
  onPageChange,
  labelKey = "pagination.label",
}: PricingPaginationProps) {
  const { t } = useTranslation("pricing");

  // With no pages there is nothing to navigate, and «page 1 of 0» must not be
  // representable (R2.3). The empty state is what the panel renders instead.
  if (totalPages <= 0) {
    return null;
  }

  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <nav
      aria-label={t(labelKey)}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3"
    >
      <p className="text-body-base text-muted-foreground">
        {t("pagination.pageOfTotal", { page, totalPages })} {t("separator")}{" "}
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
