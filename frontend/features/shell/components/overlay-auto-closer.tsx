"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { useShellUiStore } from "../state/use-shell-ui-store";

/**
 * Client island (design D9): closes ephemeral overlays whenever the pathname
 * changes. Extracted from ShellFrame so the frame itself can be a Server
 * Component. Renders nothing.
 */
export function OverlayAutoCloser() {
  const pathname = usePathname();
  const closeOverlays = useShellUiStore((state) => state.closeOverlays);

  useEffect(() => {
    closeOverlays();
  }, [pathname, closeOverlays]);

  return null;
}
