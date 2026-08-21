"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

export interface PageNavProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

/**
 * Page navigation for the inbox and for the thread (R1.6, R3.5). It moves the
 * `page` that goes into the query, so each page **replaces** the rendered content
 * instead of being appended to it — the backend paginates, the client does not
 * accumulate.
 *
 * `totalPages` comes from the page envelope (design D3); nothing is offered when
 * there is only one page.
 */
export function PageNav({ page, totalPages, onPageChange }: PageNavProps) {
  const { t } = useTranslation("conversations");

  if (totalPages <= 1) {
    return null;
  }

  return (
    <nav
      aria-label={t("pagination.label")}
      className="flex items-center justify-between gap-2"
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        {t("pagination.previous")}
      </Button>
      <span className="text-sm text-muted-foreground">
        {t("pagination.position", { page, totalPages })}
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        {t("pagination.next")}
      </Button>
    </nav>
  );
}
