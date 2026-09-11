"use client";

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

import type { UserDto } from "../../dto";
import { useActiveCleanerCount } from "../../hooks/use-active-cleaner-count";
import { useDeactivateUser } from "../../hooks/use-deactivate-user";

/**
 * Confirmation dialog calling `use-deactivate-user` (`DELETE /api/v1/users/{id}`,
 * R3.2, design D7). Only rendered by its caller (`user-row-actions.tsx`) when
 * `useHasPermission("MANAGE_USERS")` is true (design D5); this component does
 * not re-check the permission itself.
 *
 * R3.4/design D8: when the target is an `ACTIVE` `CLEANER`,
 * `use-active-cleaner-count` is fired (only while `open`, never on every row
 * render — the `enabled` flag mirrors the hook's own on-demand contract) and,
 * if `total === 1` (this row is the tenant's only active cleaner), a
 * non-blocking warning is shown alongside the confirm button — it never
 * disables or removes that button.
 *
 * The dialog body is only mounted while `open` (mirrors
 * `ManagerIncidentActions`'s `AssignSheetBody` `key="open"` pattern) so a
 * previous attempt's error state does not leak into the next time this same
 * row's dialog is reopened.
 *
 * Plain English literals (section 3 scope note, see `user-list.tsx`).
 */
export function DeactivateUserConfirm({
  user,
  open,
  onOpenChange,
}: {
  user: UserDto;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        {open ? (
          <DeactivateUserConfirmBody
            key="open"
            user={user}
            onClose={() => onOpenChange(false)}
          />
        ) : null}
      </AlertDialogContent>
    </AlertDialog>
  );
}

function DeactivateUserConfirmBody({
  user,
  onClose,
}: {
  user: UserDto;
  onClose: () => void;
}) {
  const mutation = useDeactivateUser();
  const isActiveCleaner = user.role === "CLEANER" && user.status === "ACTIVE";
  const cleanerCount = useActiveCleanerCount(isActiveCleaner);
  const isLastActiveCleaner = isActiveCleaner && cleanerCount.data === 1;

  function handleConfirm(event: { preventDefault: () => void }) {
    event.preventDefault();
    mutation.mutate(user.id, { onSuccess: () => onClose() });
  }

  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle>Deactivate user</AlertDialogTitle>
        <AlertDialogDescription>
          {`Are you sure you want to deactivate ${user.name}? They will no longer be able to sign in.`}
        </AlertDialogDescription>
      </AlertDialogHeader>
      {isLastActiveCleaner ? (
        <p role="note" className="text-sm text-state-warning-text">
          {`${user.name} is the only active cleaner in this tenant. Deactivating them will leave no one auto-assigned to checkout cleaning — this will not block the action.`}
        </p>
      ) : null}
      {mutation.isError ? (
        <p role="alert" className="text-sm text-state-error-text">
          Something went wrong while deactivating this user.
        </p>
      ) : null}
      <AlertDialogFooter>
        <AlertDialogCancel className="tap-target">Cancel</AlertDialogCancel>
        <AlertDialogAction
          className="tap-target"
          onClick={handleConfirm}
          disabled={mutation.isPending}
          aria-busy={mutation.isPending}
        >
          {mutation.isPending ? "Deactivating…" : "Deactivate"}
        </AlertDialogAction>
      </AlertDialogFooter>
    </>
  );
}
