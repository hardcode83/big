"use client";

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
 * Plain English literals (section 3 scope note, see `user-list.tsx`) — i18n
 * lands in tasks.md section 5.
 */
export function UserDetailView({ userId }: { userId: string }) {
  const query = useUser(userId);

  if (query.isPending) {
    return <LoadingState label="Loading user…" />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title="Couldn't load this user"
        description="Something went wrong while loading the user's detail."
        onRetry={() => void query.refetch()}
        retryLabel="Retry"
      />
    );
  }

  const user = query.data;
  if (!user) {
    return <EmptyState title="User not found" />;
  }

  return (
    <dl className="flex flex-col gap-3" aria-label="User detail">
      <DetailRow label="Name" value={user.name} />
      <DetailRow label="Email" value={user.email} />
      <DetailRow label="Phone" value={user.phone ?? "—"} />
      <DetailRow label="Role" value={user.role} />
      <DetailRow label="Status" value={user.status} />
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
