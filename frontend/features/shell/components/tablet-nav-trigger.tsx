"use client";

import { Menu } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useShellUiStore } from "../state/use-shell-ui-store";

/**
 * Client island (design D9): the tablet-only trigger that opens the Workspace
 * navigation drawer. Interactive (Zustand), so it stays a client leaf while the
 * shell wrapper around it is a Server Component.
 */
export function TabletNavTrigger() {
  const { t } = useTranslation("navigation");
  const open = useShellUiStore((state) => state.tabletNavOpen);
  const setOpen = useShellUiStore((state) => state.setTabletNavOpen);

  return (
    <Button
      variant="ghost"
      size="icon"
      className="hidden md:inline-flex lg:hidden"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={t("openMenu")}
      onClick={() => setOpen(true)}
    >
      <Menu />
    </Button>
  );
}
