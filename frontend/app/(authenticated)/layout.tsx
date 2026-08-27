import { getServerT } from "@/lib/i18n/server";
import { Brand } from "@/features/shell/components/brand";
import { ShellFrame } from "@/features/shell/components/shell-frame";
import { SkipLink } from "@/features/shell/components/skip-link";
import { Topbar } from "@/features/shell/components/topbar";
import { AuthGuard, UserMenu } from "@/features/auth";

/**
 * Layout for the authenticated intermediate routes (design D2, R2). The only
 * surface here today is `/welcome` (R2 #2) — a one-tap interstitial between
 * login and the role-specific shell for `CLEANER` / `TECHNICIAN`. Any
 * authenticated user passes the guard (`allow` is unset); the welcome page
 * itself decides where to send the visitor.
 *
 * **Why a new route group and not `(public)` or `(workspace)`**: the page is
 * shown AFTER login and BEFORE the shell, and needs a chrome with `UserMenu`
 * (so the field user can log out without having to navigate back to `/login`)
 * but without the sidebar/bottom-nav of any role-specific shell. `ShellFrame`
 * already supports a `topbar` slot; we compose `Brand` + `UserMenu` and skip
 * the rest of the chrome.
 *
 * Decisión del gate: `ThemeSwitcher`, `LocaleSwitcher`, `PageTitle`, and
 * `ShellFooter` are intentionally absent — `/welcome` is a transitional
 * screen, not a stable shell, and exposing them here would be noise before the
 * visitor has even chosen their shell.
 */
export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  const t = await getServerT();
  const start = <Brand label={t("common:appName")} />;
  const end = <UserMenu />;

  return (
    <AuthGuard>
      <ShellFrame
        skipLink={<SkipLink label={t("navigation:skipToContent")} />}
        topbar={await Topbar({ start, end })}
      >
        {children}
      </ShellFrame>
    </AuthGuard>
  );
}