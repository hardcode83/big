import { getServerT } from "@/lib/i18n/server";
import { Brand } from "@/features/shell/components/brand";
import { ShellFrame } from "@/features/shell/components/shell-frame";
import { SkipLink } from "@/features/shell/components/skip-link";
import { Topbar } from "@/features/shell/components/topbar";
import { AuthGuard, UserMenu } from "@/features/auth";

/**
 * Layout for the platform console (design D1, R1). `SUPER_ADMIN` belongs to no
 * tenant, so this route group deliberately does NOT reuse `(workspace)/layout.tsx`
 * (which mounts `WorkspaceShell` — a tenant selector and tenant-scoped nav, R1.4)
 * nor `(authenticated)/layout.tsx` (whose `AuthGuard` has no `allow`, so every
 * other role would see this chrome before its own redirect fires, R1.5).
 *
 * `AuthGuard allow={["SUPER_ADMIN"]}` is the explicit gate this route needs; the
 * chrome below is the same bare composition `(authenticated)/layout.tsx` uses for
 * `/welcome` — `Brand` + `UserMenu` in the topbar, no sidebar, no bottom
 * navigation, no footer (R1.3, R1.4).
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
    <AuthGuard allow={["SUPER_ADMIN"]}>
      <ShellFrame
        skipLink={<SkipLink label={t("navigation:skipToContent")} />}
        topbar={await Topbar({ start, end })}
      >
        {children}
      </ShellFrame>
    </AuthGuard>
  );
}
