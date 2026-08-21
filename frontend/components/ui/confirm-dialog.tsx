"use client";

import type { ReactNode } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";

import { Button } from "@/components/ui/button";
import { DialogShell } from "@/components/ui/dialog-shell";

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
 * A generic confirmation dialog (design D20): two buttons, both of which dismiss,
 * so Radix owns the open state and this component needs none.
 *
 * The chrome lives in `DialogShell`, which the transcription dialog also composes —
 * that one has to stay open on failure, so it cannot reuse this component itself
 * (design D13). Every string arrives by prop, so this file holds no copy.
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
    <DialogShell
      trigger={trigger}
      title={title}
      description={description}
      footer={
        <>
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
        </>
      }
    />
  );
}
