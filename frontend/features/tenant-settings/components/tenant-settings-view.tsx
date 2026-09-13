"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useHasPermission } from "@/lib/auth";

import { CreateUserForm } from "./detail/create-user-form";
import { UserList } from "./list/user-list";
import { TenantConfigForm } from "./tenant-config-form";

/**
 * `/settings` (R1-R6, design D4). Two stacked `<section>`s — "Usuarios" then
 * "Tenant" — no tabs primitive (design D4's rejected alternative): mobile-first,
 * both sections stack cleanly at 400px.
 *
 * The "Usuarios" section hosts `UserList` (which wires each row's own actions
 * via `UserRowActions`, task 3.7) plus this component's own "add user" button,
 * which opens `CreateUserForm` (task 3.3) in its own `Sheet` — `UserList`/
 * `UserRowActions` never render `CreateUserForm` themselves (tasks.md section
 * 3's implementation notes). The trigger is gated on
 * `useHasPermission("MANAGE_USERS")` (design D5), same as every other
 * mutation control in this feature.
 *
 * The "Tenant" section hosts `TenantConfigForm` directly (not sheeted, design
 * D4 — a single always-visible form, no list of items to pick from);
 * `TenantConfigForm` already self-gates read-only vs editable via
 * `useHasPermission("MANAGE_TENANT_SETTINGS")` internally, so nothing extra is
 * needed here.
 *
 * `tap-target`/keyboard-focus are applied proactively to the "add user"
 * trigger (learned from section 3's two UI/UX review rounds, applied
 * proactively in section 4 and here).
 */
export function TenantSettingsView() {
  const { t } = useTranslation("tenant-settings");
  const canManageUsers = useHasPermission("MANAGE_USERS");
  const [createUserOpen, setCreateUserOpen] = useState(false);

  return (
    <div className="flex min-w-0 flex-col gap-8 p-4">
      <section aria-labelledby="tenant-settings-users-heading" className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-2">
          <h2 id="tenant-settings-users-heading" className="text-lg font-semibold">
            {t("view.usersHeading")}
          </h2>
          {canManageUsers ? (
            <Button
              type="button"
              className="tap-target"
              onClick={() => setCreateUserOpen(true)}
            >
              {t("view.addUser")}
            </Button>
          ) : null}
        </div>
        <UserList />
      </section>

      <section aria-labelledby="tenant-settings-tenant-heading" className="flex flex-col gap-4">
        <h2 id="tenant-settings-tenant-heading" className="text-lg font-semibold">
          {t("view.tenantHeading")}
        </h2>
        <TenantConfigForm />
      </section>

      {canManageUsers ? (
        <Sheet
          open={createUserOpen}
          onOpenChange={setCreateUserOpen}
        >
          <SheetContent closeLabel={t("view.sheet.close")}>
            <SheetHeader>
              <SheetTitle>{t("view.sheet.createUserTitle")}</SheetTitle>
            </SheetHeader>
            {createUserOpen ? <CreateUserForm key="open" /> : null}
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}
