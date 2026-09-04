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

import type { TenantSummaryDto } from "../dto";
import { CreateTenantForm } from "./create-tenant-form";
import { CreateUserForm } from "./create-user-form";
import { TenantList } from "./tenant-list";

/**
 * One continuous flow, no navigation, no list refetch (R3.2, design D6). The `Sheet`
 * hosts exactly one of two forms at a time; each form owns its own success sub-view
 * (`CreateTenantForm`'s "add staff" button, `CreateUserForm`'s
 * `TemporaryPasswordReveal`) — this component only decides WHICH form is mounted.
 *
 * Two entry points open the same sheet: the "new tenant" action (`create-tenant`) and
 * any tenant row's "add staff" action (`create-user`, pre-scoped to that row's id) —
 * R4 doesn't gate the staff form to right-after-creation, so an existing tenant's first
 * hire does not require recreating the tenant.
 */
type ConsoleStep =
  | { kind: "closed" }
  | { kind: "create-tenant" }
  | { kind: "create-user"; tenantId: string; tenantName: string };

export function PlatformConsole() {
  const { t } = useTranslation("platform");
  const [step, setStep] = useState<ConsoleStep>({ kind: "closed" });

  function handleAddStaff(tenant: TenantSummaryDto) {
    setStep({ kind: "create-user", tenantId: tenant.id, tenantName: tenant.name });
  }

  return (
    <section aria-labelledby="platform-heading" className="flex min-w-0 flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <h1 id="platform-heading" className="text-lg font-semibold">
          {t("list.heading")}
        </h1>
        <Button type="button" onClick={() => setStep({ kind: "create-tenant" })}>
          {t("list.newTenant")}
        </Button>
      </div>
      <TenantList onAddStaff={handleAddStaff} />
      <Sheet
        open={step.kind !== "closed"}
        onOpenChange={(open) => {
          if (!open) setStep({ kind: "closed" });
        }}
      >
        <SheetContent closeLabel={t("sheet.close")}>
          <SheetHeader>
            <SheetTitle>
              {step.kind === "create-user"
                ? t("sheet.createUserTitle")
                : t("sheet.createTenantTitle")}
            </SheetTitle>
          </SheetHeader>
          {step.kind === "create-tenant" ? (
            <CreateTenantForm onAddStaff={handleAddStaff} />
          ) : null}
          {step.kind === "create-user" ? (
            <CreateUserForm tenantId={step.tenantId} />
          ) : null}
        </SheetContent>
      </Sheet>
    </section>
  );
}
