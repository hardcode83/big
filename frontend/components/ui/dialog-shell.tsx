"use client";

import type { ReactNode } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

export interface DialogShellProps {
  /** The control that opens the dialog; it receives focus back on close. */
  trigger: ReactNode;
  title: string;
  description: string;
  /** Optional body between the description and the actions. */
  children?: ReactNode;
  /** The action row. Wrap anything that should dismiss in `DialogPrimitive.Close`. */
  footer: ReactNode;
  /**
   * Controlled open state. Omit both to let Radix own it — which is right for a
   * dialog that always closes on either action, and wrong for one that has to stay
   * open to report a failure.
   */
  open?: boolean;
  onOpenChange?: (next: boolean) => void;
}

/**
 * The overlay/content/title/description chrome of a modal dialog, on
 * `@radix-ui/react-dialog` — already a dependency through `components/ui/sheet.tsx`,
 * so still no new package (design D20).
 *
 * Radix owns focus: it traps focus inside the content while open and returns it to
 * the trigger on close. That is the whole reason none of this is `window.confirm`,
 * which is neither localizable nor styleable nor focus-managed.
 *
 * This exists because `ConfirmDialog` could not serve every dialog on this surface:
 * it closes unconditionally on confirm, and a transcription that fails has to stay
 * open to say nothing was stored (design D13). Rather than force that case through a
 * confirm-shaped primitive, both compose this shell — which is where the actual
 * duplication was (review 2026-08-21).
 *
 * Every string arrives by prop, so this file holds no copy and no feature logic.
 */
export function DialogShell({
  trigger,
  title,
  description,
  children,
  footer,
  open,
  onOpenChange,
}: DialogShellProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 flex w-[90vw] max-w-md -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-md border bg-background p-6 shadow-lg">
          <DialogPrimitive.Title className="text-lg font-semibold text-foreground">
            {title}
          </DialogPrimitive.Title>
          <DialogPrimitive.Description className="text-sm text-muted-foreground">
            {description}
          </DialogPrimitive.Description>
          {children}
          <div className="flex flex-wrap justify-end gap-2">{footer}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
