"use client";

import type { ReactNode } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

import { Button } from "@/components/ui/button";

export interface ConfirmDialogProps {
  /** The control that opens the dialog; it receives focus back on close. */
  trigger: ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
}

/**
 * A generic confirmation dialog (design D20), built on `@radix-ui/react-dialog`,
 * which is already a dependency through `components/ui/sheet.tsx` — no new package
 * for a dialog the existing one covers.
 *
 * Radix owns focus: it traps focus inside the content while open and returns it to
 * the trigger on close. That is the whole reason this is not `window.confirm`,
 * which is neither localizable nor styleable nor focus-managed.
 *
 * Every string arrives by prop, so this file holds no copy and no feature logic.
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <DialogPrimitive.Root>
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
          <div className="flex flex-wrap justify-end gap-2">
            <DialogPrimitive.Close asChild>
              <Button type="button" variant="outline">
                {cancelLabel}
              </Button>
            </DialogPrimitive.Close>
            <DialogPrimitive.Close asChild>
              <Button type="button" onClick={onConfirm}>
                {confirmLabel}
              </Button>
            </DialogPrimitive.Close>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
