"use client";

import { useTranslation } from "react-i18next";

/**
 * Section secondary for `sender_user_id` (D8).
 *
 * - Hidden when `senderUserId` is `null` (e.g. SYSTEM or AI without
 *   user context).
 * - **No** copy-to-clipboard tooltip, **no** "Copy UUID" button, **no**
 *   specific UI affordance for the value itself.
 * - Renders a single, localized note documenting the limitation: the id
 *   cannot be resolved to a name in this view because there is no
 *   `GET /api/v1/users` with sufficient permission in the contract and
 *   opening one is out of scope for this change. The note appears **once**,
 *   inside this section; it is not duplicated elsewhere.
 */
export function ConversationThreadSenderMeta({
  senderUserId,
}: {
  senderUserId: string | null;
}) {
  const { t } = useTranslation("conversations");

  if (senderUserId === null) {
    return null;
  }

  return (
    <section
      aria-label={t("fields.senderUserIdSection")}
      className="border-t pt-2 text-xs text-muted-foreground"
    >
      <p>
        <strong>{t("fields.senderUserIdSection")}:</strong>{" "}
        <code className="font-mono">{senderUserId}</code>
      </p>
      <p>{t("fields.senderUserIdNote")}</p>
    </section>
  );
}