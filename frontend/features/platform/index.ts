export { PlatformConsole } from "./components/platform-console";

export { useTenants } from "./hooks/use-tenants";
export { useCreateTenant } from "./hooks/use-create-tenant";
export { useCreatePlatformUser } from "./hooks/use-create-platform-user";

export { getPlatformDataSource } from "./data";
export { mapFieldErrors } from "./lib/field-errors";
export { platformKeys } from "./hooks/query-keys";

export type {
  CreatePlatformUserInput,
  CreateTenantInput,
  CreatedPlatformUserDto,
  PlatformUserDto,
  TenantConfigDto,
  TenantListDto,
  TenantSummaryDto,
  TenantStatus,
  UserRole,
  UserStatus,
} from "./dto";
