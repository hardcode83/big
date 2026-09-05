"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { TenantSummaryDto } from "../dto";
import { useTenants } from "../hooks/use-tenants";
import { PlatformPagination } from "./platform-pagination";

const PER_PAGE = 20;

function formatDate(value: string): string {
  return value.slice(0, 10);
}

/**
 * The tenant list of `/platform` (R2.6, design D6). Renders `useTenants`'
 * data — name, status, `created_at` per row — with a per-row "add staff"
 * action, and `PlatformPagination` only once `totalPages` exceeds one (R2.6).
 *
 * `page` lives in local `useState`: there is no URL sync and no other view
 * reads it (same reasoning `ConversationsView` gives for its own filters).
 * Deliberately NOT invalidated or refetched by `useCreateTenant` (design D6) —
 * this component's own next natural render (revisit, refocus, manual
 * re-open) is what picks up a tenant created moments ago.
 */
export function TenantList({
  onAddStaff,
}: {
  onAddStaff: (tenant: TenantSummaryDto) => void;
}) {
  const { t } = useTranslation(["platform", "states"]);
  const [page, setPage] = useState(1);
  const query = useTenants(page, PER_PAGE);

  if (query.isPending) {
    return <LoadingState label={t("states:loading.label")} />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title={t("platform:list.error.title")}
        description={t("platform:list.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={t("states:error.retry")}
      />
    );
  }

  const { items, total, totalPages } = query.data;

  if (items.length === 0) {
    return (
      <EmptyState
        title={t("platform:list.empty.title")}
        description={t("platform:list.empty.description")}
      />
    );
  }

  return (
    <div className="flex min-w-0 flex-col">
      {/* R5.2: the table's minimum content width exceeds a narrow mobile viewport —
        * this wrapper scrolls the table itself instead of the whole page overflowing
        * (`min-w-0` on the outer flex column only lets the item shrink, it does not
        * clip or scroll the table inside it). */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("platform:list.label")}</caption>
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th scope="col" className="px-4 py-2 font-medium">
                {t("platform:list.columns.name")}
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                {t("platform:list.columns.status")}
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                {t("platform:list.columns.createdAt")}
              </th>
              <th scope="col" className="px-4 py-2 font-medium">
                <span className="sr-only">{t("platform:list.addStaff")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((tenant) => (
              <tr key={tenant.id} className="border-b last:border-b-0">
                <td className="px-4 py-2">{tenant.name}</td>
                <td className="px-4 py-2">{t(`platform:status.${tenant.status}`)}</td>
                <td className="px-4 py-2">{formatDate(tenant.createdAt)}</td>
                <td className="px-4 py-2 text-right">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onAddStaff(tenant)}
                  >
                    {t("platform:list.addStaff")}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 ? (
        <PlatformPagination
          page={page}
          totalPages={totalPages}
          total={total}
          onPageChange={setPage}
        />
      ) : null}
    </div>
  );
}
