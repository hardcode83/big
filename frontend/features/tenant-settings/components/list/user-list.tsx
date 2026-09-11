"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import type { UserDto, UserRole, UserStatus } from "../../dto";
import { useUsers } from "../../hooks/use-users";
import { UserRowActions } from "./user-row-actions";

/**
 * NOTE (section 3 scope): every visible string in this file is a plain English
 * literal, not `t(...)`. i18n lands in tasks.md section 5 (locale JSON files +
 * registration) — this component intentionally has no `useTranslation` call
 * yet, so it is not (re)wired twice.
 */
const ROLE_OPTIONS: readonly UserRole[] = [
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
  "SUPER_ADMIN",
];

const STATUS_OPTIONS: readonly UserStatus[] = ["ACTIVE", "INACTIVE", "SUSPENDED"];

/**
 * The paginated user directory of `/settings`'s "Usuarios" section (R1.1,
 * R1.2, design D4). Owns the filters state and `useUsers(filters)`'s
 * loading/empty/error states (`steering/frontend.md`'s UI-states rule); a
 * populated page renders a table whose rows each mount `UserRowActions`
 * (design D4's row-opens-a-Sheet pattern, task 3.7) so row selection opens the
 * read-only detail (R1.3) for any role, plus the mutation controls when
 * `useHasPermission("MANAGE_USERS")` is true (task 3.7, design D5).
 */
export function UserList() {
  const [filters, setFilters] = useState<{ role?: UserRole; status?: UserStatus }>({});
  const query = useUsers(filters);

  return (
    <div className="flex flex-col gap-4">
      <UserListFilters value={filters} onChange={setFilters} />
      <UserListBody query={query} />
    </div>
  );
}

function UserListFilters({
  value,
  onChange,
}: {
  value: { role?: UserRole; status?: UserStatus };
  onChange: (next: { role?: UserRole; status?: UserStatus }) => void;
}) {
  return (
    <div
      className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface/60 p-3"
      aria-label="Filter users"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="user-filter-role" className="text-xs font-medium text-muted-foreground">
          Role
        </label>
        <select
          id="user-filter-role"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={value.role ?? ""}
          onChange={(event) => {
            const role = (event.target.value || undefined) as UserRole | undefined;
            onChange({ ...value, role });
          }}
        >
          <option value="">All roles</option>
          {ROLE_OPTIONS.map((role) => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="user-filter-status" className="text-xs font-medium text-muted-foreground">
          Status
        </label>
        <select
          id="user-filter-status"
          className="tap-target rounded-md border bg-background px-2 py-1 text-sm"
          value={value.status ?? ""}
          onChange={(event) => {
            const status = (event.target.value || undefined) as UserStatus | undefined;
            onChange({ ...value, status });
          }}
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </div>
      <button
        type="button"
        className="tap-target rounded-md border bg-background px-3 py-1 text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
        onClick={() => onChange({})}
      >
        Clear filters
      </button>
    </div>
  );
}

function UserListBody({
  query,
}: {
  query: ReturnType<typeof useUsers>;
}) {
  if (query.isPending) {
    return <LoadingState label="Loading users…" />;
  }

  if (query.isError) {
    return (
      <ErrorState
        title="Couldn't load users"
        description="Something went wrong while loading the user directory."
        onRetry={() => void query.refetch()}
        retryLabel="Retry"
      />
    );
  }

  const page = query.data;

  if (page.data.length === 0) {
    return (
      <EmptyState
        title="No users found"
        description="No user matches the current filters."
      />
    );
  }

  return (
    <div className="flex min-w-0 flex-col">
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">Tenant users</caption>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                Name
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                Email
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                Role
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                Status
              </th>
              <th scope="col" className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {page.data.map((user) => (
              <UserRow key={user.id} user={user} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function UserRow({ user }: { user: UserDto }) {
  return (
    <tr className="border-b border-border last:border-b-0 hover:bg-accent/50">
      <td className="px-4 py-3">{user.name}</td>
      <td className="px-4 py-3">{user.email}</td>
      <td className="px-4 py-3">
        <Badge variant="outline">{user.role}</Badge>
      </td>
      <td className="px-4 py-3">
        <Badge variant="outline">{user.status}</Badge>
      </td>
      <td className="px-4 py-3 text-right">
        <UserRowActions user={user} />
      </td>
    </tr>
  );
}
