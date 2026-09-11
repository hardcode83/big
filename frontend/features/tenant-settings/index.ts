// Barrel for the tenant-settings feature. The App Router page imports the
// view component from here; the data layer and hooks are also re-exported so
// a single `@/features/tenant-settings` import brings the whole feature into
// scope (mirrors `features/reservations/index.ts`).
export { TenantSettingsView } from "./components/tenant-settings-view";

export { useUsers } from "./hooks/use-users";
export { useUser } from "./hooks/use-user";
export { useCreateUser } from "./hooks/use-create-user";
export { useUpdateUser } from "./hooks/use-update-user";
export { useDeactivateUser } from "./hooks/use-deactivate-user";
export { useResetPassword } from "./hooks/use-reset-password";
export { useActiveCleanerCount } from "./hooks/use-active-cleaner-count";
export { useTenant } from "./hooks/use-tenant";
export { useUpdateTenant } from "./hooks/use-update-tenant";
export { tenantSettingsKeys } from "./hooks/query-keys";

export { getTenantSettingsDataSource } from "./data";

export type * from "./dto";
