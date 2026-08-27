"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { LogOut } from "lucide-react";

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
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth";

const EMAIL_MAX = 24;

/**
 * Topbar user control for the three authenticated shells (workspace, cleaner,
 * technician). The trigger shows the authenticated user's email truncated to
 * 24 characters (with an ellipsis past that) so a user on a shared device can
 * always tell who is signed in. The single menu item opens an `AlertDialog`
 * that confirms the logout before it runs (design D4).
 *
 * **Why confirmation, and not just logout on click**: SaaS pattern is one
 * click, but on a shared device (a technician's tablet at the property, a
 * manager's laptop shared at the front desk) a stray tap closes the session
 * and forces a fresh login. One extra click costs nothing and saves that.
 *
 * **Sequence on confirm (design D5)**: `useAuth().logout()` first — that POSTs
 * `/auth/logout` (best-effort; the catch in `auth-provider.tsx:126-127` keeps
 * the local purge unconditional), purges tokens, the `autohostai.session.present`
 * cookie, and the TanStack Query cache — then `router.replace("/")` so the
 * back button does not return to a now-unauthenticated route, and finally
 * `router.refresh()` so `app/page.tsx:35` re-evaluates the just-cleared
 * cookie and the landing renders.
 *
 * The dialog is closed BEFORE `await logout()` runs — `setOpen(false)` first,
 * then the network call — so the dialog does not block on the round-trip and
 * a slow network does not strand the user with the spinner visible.
 */
export function UserMenu() {
  const { t } = useTranslation(["navigation", "auth"]);
  const { user, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  const email = user?.email;
  const fallbackLabel = t("navigation:userMenu.anonymous");
  const triggerLabel = email && email.length > EMAIL_MAX
    ? `${email.slice(0, EMAIL_MAX - 1)}…`
    : (email ?? fallbackLabel);
  const ariaTriggerLabel = t("navigation:userMenu.triggerLabel");

  async function handleLogout() {
    setOpen(false);
    try {
      await logout();
    } catch {
      // Best-effort: `auth-provider.tsx:126-127` already swallows network
      // errors and purges local state. We catch defensively too, in case a
      // future implementation forgets — the redirect must still happen so
      // the visitor lands on the public landing, not on a stale authenticated
      // page.
    } finally {
      router.replace("/");
      router.refresh();
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="default"
            className="tap-target max-w-48 truncate px-3 text-sm font-normal"
            aria-label={ariaTriggerLabel}
          >
            {triggerLabel}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={(event) => {
              event.preventDefault();
              setOpen(true);
            }}
          >
            <LogOut aria-hidden="true" />
            {t("navigation:userMenu.logout")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("auth:logoutConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("auth:logoutConfirmBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>
              {t("auth:logoutConfirmCancel")}
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleLogout}>
              {t("auth:logoutConfirmAction")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}