"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { ShellRouteDescriptor } from "../navigation/route-registry";
import { NavLink } from "./nav-link";

/**
 * The "More" sheet holding the primary destinations that do not fit in the
 * mobile bottom navigation (design D6). `children` is the trigger (rendered via
 * SheetTrigger asChild) so Radix wires aria-expanded and focus return natively,
 * while the store still controls `open` so overlays close on navigation.
 */
export function MoreMenu({
  routes,
  open,
  onOpenChange,
  children,
}: {
  routes: readonly ShellRouteDescriptor[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("navigation");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>{children}</SheetTrigger>
      <SheetContent side="bottom" closeLabel={t("closeMenu")}>
        <SheetHeader>
          <SheetTitle>{t("more")}</SheetTitle>
        </SheetHeader>
        <ul className="flex flex-col gap-1">
          {routes.map((route) => (
            <li key={route.id}>
              <NavLink route={route} onNavigate={() => onOpenChange(false)} />
            </li>
          ))}
        </ul>
      </SheetContent>
    </Sheet>
  );
}
