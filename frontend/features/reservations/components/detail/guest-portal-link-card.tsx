"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useHasPermission } from "@/lib/auth";

import {
  useGuestAccessTokenStatus,
  useIssueGuestAccessToken,
  useRevokeGuestAccessToken,
  useSendGuestAccessTokenEmail,
} from "../../hooks/use-guest-access-token";

/**
 * Mint, copy, revoke and email the reservation's guest portal token, from
 * `/reservations/[id]` itself (proposal R1, R3, design D7).
 *
 * **Gated by `MANAGE_GUEST_ACCESS_TOKENS` (R1.4)** — `useHasPermission` is
 * called unconditionally alongside the other four hooks (rules-of-hooks: a
 * conditional `return null` is only safe *after* every hook of the render has
 * already run), and the whole section renders nothing when the permission is
 * absent. This is a UX courtesy, not the security boundary
 * (`steering/frontend.md`: "RBAC del backend decide, el frontend solo
 * oculta") — the backend 403s regardless.
 *
 * The status query is passed `enabled: hasPermission` so a viewer without the
 * permission never even issues the request the backend would refuse — an
 * optimization on top of the hidden UI, not a substitute for it.
 *
 * **The one-time reveal (R1.2)** mirrors
 * `features/platform/components/temporary-password-reveal.tsx` field for
 * field: a read-only monospace value, a copy-to-clipboard button that flips
 * to a "copied" label, and a persistent warning that it will not be shown
 * again. It never writes the token to `localStorage`, a query string, or
 * router history. `useIssueGuestAccessToken`'s `gcTime: 0` is what makes
 * "never re-displayed after unmount" true: the mutation (and the cleartext
 * value in `mutation.data`) is garbage-collected from TanStack Query's
 * module-level `MutationCache` the instant this component has no observer,
 * so remounting (leaving the screen and returning to it) starts from a fresh
 * mutation with no data.
 *
 * **Revoke (R1.3)** and **send (R3)** both invalidate the status query on
 * success (inside their own hooks), so the visible status updates without a
 * page reload.
 *
 * **R1.5**: each action's own button disables while that action's own
 * mutation `isPending` — matching design D7's "all four disable their
 * triggering control while `isPending`" verbatim, not a broader cross-lock
 * between the three buttons.
 */
export function GuestPortalLinkCard({
  reservationId,
}: {
  reservationId: string;
}) {
  const { t } = useTranslation("reservations");
  const hasPermission = useHasPermission("MANAGE_GUEST_ACCESS_TOKENS");
  const statusQuery = useGuestAccessTokenStatus(reservationId, hasPermission);
  const issueMutation = useIssueGuestAccessToken(reservationId);
  const revokeMutation = useRevokeGuestAccessToken(reservationId);
  const sendMutation = useSendGuestAccessTokenEmail(reservationId);
  const [copied, setCopied] = useState(false);

  if (!hasPermission) {
    return null;
  }

  async function handleCopy() {
    if (!issueMutation.data) {
      return;
    }
    await navigator.clipboard.writeText(issueMutation.data);
    setCopied(true);
  }

  function handleIssue() {
    setCopied(false);
    issueMutation.mutate();
  }

  return (
    <section
      aria-label={t("guestPortalLink.title")}
      className="flex flex-col gap-3"
    >
      <h2 className="text-sm font-medium">{t("guestPortalLink.title")}</h2>

      <p role="status">
        {statusQuery.isPending
          ? t("guestPortalLink.status.loading")
          : statusQuery.data?.isLive
            ? t("guestPortalLink.status.live", {
                issuedAt: statusQuery.data.issuedAt,
              })
            : t("guestPortalLink.status.none")}
      </p>

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={issueMutation.isPending}
          onClick={handleIssue}
        >
          {t("guestPortalLink.actions.mint")}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={revokeMutation.isPending}
          onClick={() => revokeMutation.mutate()}
        >
          {t("guestPortalLink.actions.revoke")}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={sendMutation.isPending}
          onClick={() => sendMutation.mutate()}
        >
          {t("guestPortalLink.actions.send")}
        </Button>
      </div>

      {issueMutation.isError ? (
        <p role="alert">{t("guestPortalLink.feedback.error")}</p>
      ) : null}
      {revokeMutation.isError ? (
        <p role="alert">{t("guestPortalLink.feedback.error")}</p>
      ) : null}

      {issueMutation.data ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <code className="flex-1 rounded-md border bg-muted px-3 py-2 font-mono text-sm">
              {issueMutation.data}
            </code>
            <Button type="button" variant="outline" onClick={() => void handleCopy()}>
              {copied
                ? t("guestPortalLink.reveal.copied")
                : t("guestPortalLink.reveal.copy")}
            </Button>
          </div>
          <p className="text-sm font-medium text-state-warning-text">
            {t("guestPortalLink.reveal.warning")}
          </p>
        </div>
      ) : null}

      {sendMutation.isSuccess ? (
        <p role="status">
          {sendMutation.data
            ? t("guestPortalLink.feedback.delivered")
            : t("guestPortalLink.feedback.notDelivered")}
        </p>
      ) : null}
      {sendMutation.isError ? (
        <p role="alert">{t("guestPortalLink.feedback.error")}</p>
      ) : null}
    </section>
  );
}
