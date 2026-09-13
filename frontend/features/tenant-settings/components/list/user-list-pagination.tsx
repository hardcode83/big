"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * Presentational page navigation for the user directory (R1.1's "listado
 * paginado"). Same shape as the four page navigations already in the tree —
 * `cleaning-pagination.tsx`, `pricing-pagination.tsx`,
 * `platform-pagination.tsx` and `cleaner-task-pagination.tsx` — each of which
 * hardcodes its own i18n namespace. `PlatformPagination` is the closest
 * (identical props, same `{data, total, page, per_page, total_pages}`
 * envelope) but is not reusable here: it reads `useTranslation("platform")`
 * and its strings are written about tenants ("{{total}} tenants en total"), so
 * mounting it on the user directory would print the wrong noun in the wrong
 * namespace. This is the fifth near-copy of that shape rather than a shared,
 * namespace-parameterized component, because extracting one would mean
 * touching four other features outside this change's scope.
 *
 * It owns no state: `page`, `totalPages` and `total` come from the response
 * envelope the backend returned, and moving is `onPageChange`'s business.
 */
export interface UserListPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function UserListPagination({
  page,
  totalPages,
  total,
  onPageChange,
}: UserListPaginationProps) {
  const { t } = useTranslation("tenant-settings");
  const isFirst = page <= 1;
  const isLast = page >= totalPages;

  return (
    <nav
      aria-label={t("userList.pagination.label")}
      className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3"
    >
      <p className="text-sm text-muted-foreground">
        {t("userList.pagination.pageOfTotal", { page, totalPages })}{" "}
        {t("userList.pagination.totalUsers", { total })}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={isFirst}
          onClick={() => onPageChange(page - 1)}
        >
          {t("userList.pagination.previous")}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={isLast}
          onClick={() => onPageChange(page + 1)}
        >
          {t("userList.pagination.next")}
        </Button>
      </div>
    </nav>
  );
}
