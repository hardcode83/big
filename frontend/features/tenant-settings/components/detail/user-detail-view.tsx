"use client";

import { useTranslation } from "react-i18next";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { useUser } from "../../hooks/use-user";

/**
 * Read-only rendering of one user (R1.3) via `use-user`. Opened for **any**
 * row regardless of the acting role: a `PROPERTY_MANAGER` has backend read
 * access to `GET /api/v1/users/{id}` same as the list
 * (`user-management` §Aislamiento), so this view is never gated by
 * `useHasPermission` — only the mutation layers on top of it (edit/deactivate/
 * reset-password, tasks 3.4-3.6) are.
 *
 * Includes `INACTIVE`/`SUSPENDED` users: the backend does not hide non-`ACTIVE`
 * rows from this endpoint, and this view renders whatever status comes back
 * with no special-casing.
 *
 * i18n (section 5): the `tenant-settings` namespace. `role`/`status` labels
 * are translated; `name`/`email`/`phone` are the raw DTO values, never
 * localized/formatted.
 */
export function UserDetailView({ userId }: { userId: string }) {
  const { t } = useTranslation("tenant-settings");
  const query = useUser(userId);

  if (query.isPending) {
    return <LoadingState label={t("userDetail.loading")} />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title={t("userDetail.error.title")}
        description={t("userDetail.error.description")}
        onRetry={() => void query.refetch()}
        retryLabel={t("userDetail.error.retry")}
      />
    );
  }

  const user = query.data;
  if (!user) {
    return <EmptyState title={t("userDetail.notFound")} />;
  }

  return (
    <dl className="flex flex-col gap-3" aria-label={t("userDetail.ariaLabel")}>
      <DetailRow label={t("userDetail.fields.name")} value={user.name} />
      <DetailRow label={t("userDetail.fields.email")} value={user.email} />
      <DetailRow label={t("userDetail.fields.phone")} value={user.phone ?? t("userDetail.unset")} />
      <DetailRow label={t("userDetail.fields.role")} value={t(`userRole.${user.role}`)} />
      <DetailRow label={t("userDetail.fields.status")} value={t(`userStatus.${user.status}`)} />
    </dl>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{value}</dd>
    </div>
  );
}
