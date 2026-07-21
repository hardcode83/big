import {
  BadgeCheck,
  Building2,
  CalendarCheck,
  CalendarClock,
  ClipboardList,
  DoorOpen,
  KeyRound,
  LayoutDashboard,
  LogIn,
  MessagesSquare,
  Plug,
  Receipt,
  Settings,
  Sparkles,
  Star,
  Tag,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { NavigationIconName } from "../navigation/route-registry";

/** Resolves a serializable icon name from the registry to a lucide component. */
export const navigationIcons: Record<NavigationIconName, LucideIcon> = {
  LayoutDashboard,
  CalendarClock,
  Building2,
  CalendarCheck,
  Sparkles,
  Wrench,
  MessagesSquare,
  BadgeCheck,
  Tag,
  Receipt,
  Star,
  Settings,
  Plug,
  LogIn,
  KeyRound,
  ClipboardList,
  DoorOpen,
};
