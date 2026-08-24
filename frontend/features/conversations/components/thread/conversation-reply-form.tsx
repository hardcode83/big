"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api";

import { useReplyToConversation } from "../../hooks/use-reply-to-conversation";

/**
 * Map the mutation error to a localized error key (R6.4). The envelope
 * (`message`, `details`, `code`) is intentionally never read — the keys
 * here are exhaustive over the status codes that the UI distinguishes.
 * Anything not enumerated falls back to the generic copy. The body the
 * caller passes is `null` while the mutation has not been attempted.
 */
function replyErrorKey(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return "thread.replyErrorValidation";
    if (error.status === 401) return "thread.replyErrorUnauthorized";
    if (error.status === 403) return "thread.replyErrorForbidden";
    if (error.status === 404) return "thread.replyErrorNotFound";
  }
  return "thread.replyErrorGeneric";
}

/**
 * The reply form of a conversation (proposal R4, design D9).
 *
 * **Single source of truth for the draft**: the form owns its draft via
 * `useState` exclusively. The draft is **never** propagated to the
 * mutation hook — `useReplyToConversation` only knows the mutation, the
 * retry policy and the cache invalidation. On success the form clears
 * the field; on error the form **does not modify** the draft (the
 * backend's `422` is surfaced as a localized copy).
 *
 * The visible character counter is **information**, not a hard stop:
 * the button is **never** disabled by proximity to the 4000-char cap
 * (`MAX_MESSAGE_CONTENT_LENGTH`, declared in `messaging-ai.md` R3 and
 * enforced by the `CreateMessageRequest` Pydantic schema). The length
 * rejection lives in the backend and surfaces as a localized error after
 * the mutation resolves — the draft is preserved in the field, ready
 * for the operator to trim. The button is disabled **only** while the
 * mutation is in flight (a single, explicit reason that matches
 * `useMutation`'s state).
 */
export function ConversationReplyForm({
  conversationId,
  onReplySuccess,
}: {
  conversationId: string;
  /**
   * Called once, after a successful submission, so the parent can
   * reset any thread-local state (e.g. the page of a paginated thread).
   * The hook itself does NOT call this — it owns the mutation and the
   * cache invalidation, but the form is the only owner of the draft
   * and the parent's `useState` for the page is not visible here.
   */
  onReplySuccess?: () => void;
}) {
  const { t } = useTranslation("conversations");
  const [draft, setDraft] = useState("");
  const mutation = useReplyToConversation(conversationId);

  const isInFlight = mutation.isPending;
  const error = mutation.error;

  const submitReply = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    mutation.mutate({ content: draft });
  };

  // On success, clear the draft and notify the parent. This is React's
  // "adjusting state during render" pattern: the branch is only taken on
  // the render where `isSuccess` first flips true with a non-empty draft,
  // and React re-renders synchronously before painting, so the visible UI
  // is always the cleared form. `useEffect` is intentionally not used:
  // the form is the only owner of the draft, so there is nothing to
  // synchronize with another store.
  if (mutation.isSuccess && draft !== "" && !isInFlight) {
    setDraft("");
    onReplySuccess?.();
  }

  return (
    <form onSubmit={submitReply} aria-label={t("thread.replyHeading")}>
      <label className="mb-1 block text-xs font-medium" htmlFor="reply-content">
        {t("thread.replyHeading")}
      </label>
      <textarea
        id="reply-content"
        rows={4}
        className="w-full rounded-md border bg-background p-2 text-sm"
        placeholder={t("thread.replyPlaceholder")}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        disabled={isInFlight}
        aria-describedby="reply-counter"
      />
      <div
        id="reply-counter"
        className="mt-1 flex items-center justify-between text-xs text-muted-foreground"
      >
        <span>{t("fields.characterCount", { count: draft.length })}</span>
        <button
          type="submit"
          disabled={isInFlight}
          className="rounded-md border bg-background px-3 py-1 text-sm font-medium"
        >
          {isInFlight ? t("thread.replySending") : t("thread.replySubmit")}
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {t(replyErrorKey(error))}
        </p>
      ) : null}
    </form>
  );
}