"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useAuth, useHasPermission } from "@/lib/auth";

import type { UserDto } from "../../dto";
import { DeactivateUserConfirm } from "../detail/deactivate-user-confirm";
import { EditUserForm } from "../detail/edit-user-form";
import { ResetPasswordConfirm } from "../detail/reset-password-confirm";
import { UserDetailView } from "../detail/user-detail-view";

type SheetStep = "closed" | "view" | "edit";

/**
 * Per-row actions for `user-list.tsx` (task 3.7, design D4). Wires 3.2
 * (`UserDetailView`, always) plus 3.3-3.6's mutation layers (only when
 * `useHasPermission("MANAGE_USERS")`) into one `Sheet`, mirroring
 * `platform-console.tsx`'s single-`Sheet`-hosts-one-form pattern: the `Sheet`
 * hosts exactly one of "view" (detail + action buttons) or "edit"
 * (`EditUserForm`) at a time. Deactivate and reset-password are their own
 * `AlertDialog`s (design D13 precedent, `manager-incident-actions.tsx`),
 * layered alongside the `Sheet` and opened from buttons inside the "view"
 * step.
 *
 * For a `PROPERTY_MANAGER` session (no `MANAGE_USERS`) the `Sheet` hosts only
 * the read-only `UserDetailView`, never the mutation forms — their imports
 * are simply not rendered (design D5's "hidden, not disabled" contract), and
 * neither `DeactivateUserConfirm` nor `ResetPasswordConfirm` mount at all.
 *
 * R3.3: the "Deactivate" action is also disabled for the acting user's own
 * row — deactivation is a status change on oneself, the same class of action
 * R3.3 disables role/status controls for.
 *
 * Plain English literals (section 3 scope note, see `user-list.tsx`).
 */
export function UserRowActions({ user }: { user: UserDto }) {
  const { user: sessionUser } = useAuth();
  const canManage = useHasPermission("MANAGE_USERS");
  const [step, setStep] = useState<SheetStep>("closed");
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);

  const isSelf = sessionUser?.id === user.id;

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="tap-target"
        onClick={() => setStep("view")}
      >
        View
      </Button>
      <Sheet
        open={step !== "closed"}
        onOpenChange={(open) => {
          if (!open) setStep("closed");
        }}
      >
        <SheetContent closeLabel="Close">
          <SheetHeader>
            <SheetTitle>{step === "edit" ? "Edit user" : "User detail"}</SheetTitle>
          </SheetHeader>
          {step === "view" ? (
            <div className="flex flex-col gap-4">
              <UserDetailView userId={user.id} />
              {canManage ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="tap-target"
                    onClick={() => setStep("edit")}
                  >
                    Edit
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="tap-target"
                    onClick={() => setResetOpen(true)}
                  >
                    Reset password
                  </Button>
                  {user.status === "ACTIVE" ? (
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      className="tap-target"
                      disabled={isSelf}
                      onClick={() => setDeactivateOpen(true)}
                    >
                      Deactivate
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
          {step === "edit" && canManage ? (
            <EditUserForm userId={user.id} onSuccess={() => setStep("view")} />
          ) : null}
        </SheetContent>
      </Sheet>
      {canManage ? (
        <>
          <DeactivateUserConfirm
            user={user}
            open={deactivateOpen}
            onOpenChange={setDeactivateOpen}
          />
          <ResetPasswordConfirm
            userId={user.id}
            userName={user.name}
            open={resetOpen}
            onOpenChange={setResetOpen}
          />
        </>
      ) : null}
    </>
  );
}
