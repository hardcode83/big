/**
 * Limits this surface enforces before the backend has to (R4.3).
 *
 * This lives in `lib/` with the other contract-derived facts of the feature —
 * `labels.ts`, `transitions.ts`, `permissions.ts`, `channels.ts` — and not in the
 * component that happens to use it first. It was declared in `reply-composer.tsx`
 * and imported from `transcribe-dialog.tsx`, which made it the one contract fact
 * travelling component-to-component (review 2026-08-21, design D1).
 */

/** `CreateMessageRequest.content` is capped at 4000 characters by the contract. */
export const MAX_MESSAGE_LENGTH = 4000;
