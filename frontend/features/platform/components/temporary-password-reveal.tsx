"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * The one-time temporary password (R4.3, R4.4, design D7). A read-only monospace field,
 * a copy-to-clipboard button, and a persistent visible warning that it will not be shown
 * again — matching the backend's own "exactly once" contract.
 *
 * `temporaryPassword` is a prop, read from the mutation's own response (`CreateUserForm`'s
 * `mutation.data`); this component never writes it to `localStorage`, a query string, or
 * router history, and never logs it. Closing the `Sheet` unmounts this component and drops
 * its own `copied` state — there is no "show it again" path in the UI tree. The value's
 * actual retention past that point is `useCreatePlatformUser`'s concern (see its `gcTime: 0`,
 * R4.4): TanStack Query's `MutationCache` is a module-level singleton that would otherwise
 * outlive this component's unmount.
 */
export function TemporaryPasswordReveal({
  temporaryPassword,
  userName,
}: {
  temporaryPassword: string;
  userName: string;
}) {
  const { t } = useTranslation("platform");
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(temporaryPassword);
    setCopied(true);
  }

  return (
    <div className="flex flex-col gap-3">
      <p role="status">{t("temporaryPassword.created", { name: userName })}</p>
      <div className="flex items-center gap-2">
        <code className="flex-1 rounded-md border bg-muted px-3 py-2 font-mono text-sm">
          {temporaryPassword}
        </code>
        <Button type="button" variant="outline" onClick={() => void handleCopy()}>
          {copied ? t("temporaryPassword.copied") : t("temporaryPassword.copy")}
        </Button>
      </div>
      <p className="text-sm font-medium text-state-warning-text">
        {t("temporaryPassword.warning")}
      </p>
    </div>
  );
}
