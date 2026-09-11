"use client";

import { useTranslation } from "react-i18next";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { TemporaryPasswordReveal } from "@/features/platform";

import { useResetPassword } from "../../hooks/use-reset-password";

/**
 * Confirm dialog calling `use-reset-password`
 * (`POST /api/v1/users/{id}/reset-password`, R4.1). Only rendered by its
 * caller (`user-row-actions.tsx`) when `useHasPermission("MANAGE_USERS")` is
 * true (design D5); this component does not re-check the permission itself.
 *
 * On success this dialog switches itself to the reused
 * `TemporaryPasswordReveal` (same component as `CreateUserForm`'s R2.1
 * reveal). The dialog body is only mounted while `open` (same
 * `key="open"` pattern as `DeactivateUserConfirm`) so `useResetPassword`'s
 * `gcTime: 0` mutation state (holding the one-time secret) does not survive
 * to the next time this row's dialog is reopened — mirrors
 * `guest-portal-link-card.tsx`'s unmount/remount guarantee.
 *
 * i18n (section 5): the `tenant-settings` namespace, incl. the interpolated
 * `{{name}}` in the confirmation description.
 */
export function ResetPasswordConfirm({
  userId,
  userName,
  open,
  onOpenChange,
}: {
  userId: string;
  userName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        {open ? (
          <ResetPasswordConfirmBody key="open" userId={userId} userName={userName} />
        ) : null}
      </AlertDialogContent>
    </AlertDialog>
  );
}

function ResetPasswordConfirmBody({
  userId,
  userName,
}: {
  userId: string;
  userName: string;
}) {
  const { t } = useTranslation("tenant-settings");
  const mutation = useResetPassword();

  function handleConfirm(event: { preventDefault: () => void }) {
    event.preventDefault();
    mutation.mutate(userId);
  }

  if (mutation.isSuccess) {
    return (
      <>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("resetPasswordConfirm.successTitle")}</AlertDialogTitle>
        </AlertDialogHeader>
        <TemporaryPasswordReveal
          temporaryPassword={mutation.data.temporaryPassword}
          userName={mutation.data.user.name}
        />
        <AlertDialogFooter>
          <AlertDialogCancel className="tap-target">{t("resetPasswordConfirm.close")}</AlertDialogCancel>
        </AlertDialogFooter>
      </>
    );
  }

  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle>{t("resetPasswordConfirm.title")}</AlertDialogTitle>
        <AlertDialogDescription>
          {t("resetPasswordConfirm.description", { name: userName })}
        </AlertDialogDescription>
      </AlertDialogHeader>
      {mutation.isError ? (
        <p role="alert" className="text-sm text-state-error-text">
          {t("resetPasswordConfirm.error")}
        </p>
      ) : null}
      <AlertDialogFooter>
        <AlertDialogCancel className="tap-target">{t("resetPasswordConfirm.cancel")}</AlertDialogCancel>
        <AlertDialogAction
          className="tap-target"
          onClick={handleConfirm}
          disabled={mutation.isPending}
          aria-busy={mutation.isPending}
        >
          {mutation.isPending ? t("resetPasswordConfirm.confirming") : t("resetPasswordConfirm.confirm")}
        </AlertDialogAction>
      </AlertDialogFooter>
    </>
  );
}
