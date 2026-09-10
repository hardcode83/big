# Archive notes: reservation-manual-guest-resolution

These notes are for `/sdd:archive` after the change is merged. They are not living
specifications and must not be applied to `sdd/specs/` during `/sdd:run`.

## `sdd/specs/reservations.md`

Add the manual reservation contract for `POST /api/v1/reservations`:

- `guest_id` alone remains valid and must resolve an existing Guest in the acting tenant;
  an absent or cross-tenant id returns the existing `404` error envelope.
- `guest` alone is valid. It requires `full_name` trimmed to 1–300 characters; optional
  email is trimmed/lowercased with blank treated as absent; optional phone uses the existing
  normalization; `preferred_language` is `es` or `en`, defaulting to `es`.
- Omitting both fields is valid for a guest-less reservation. Supplying both `guest_id` and
  `guest` returns the existing `422` validation envelope and performs no writes.
- The creation response keeps `guest_id` nullable for guest-less reservations and returns
  the resolved id for a `guest` request. Existing response and error envelopes remain.

## `sdd/specs/domain-foundation-core.md`

Record that manual guest resolution is an application-level policy, not a database identity
guarantee. Email is the only automatic matching key; a reused Guest is not updated. When
historical duplicates exist, the repository's deterministic selection is the earliest
`created_at`, then the lowest `id`. The policy does not merge, delete, or reassign historical
Guests, reservations, or conversations.

The database intentionally retains the non-unique tenant/email index: this change adds no
`UNIQUE` constraint. A separate, explicitly approved identity-hardening change is required
for a database uniqueness guarantee and any duplicate reconciliation policy.

## `sdd/specs/ingest.md`

No file exists today, so there is no file to update. At archive, create a dedicated
`sdd/specs/ingest.md` to extract the ingest-specific adoption of the shared resolver: its
DTO mapping/defaults, guest-less rows, tenant scope, transaction-owned advisory lock, and
batch rollback semantics. Do not duplicate the manual HTTP contract there; cross-reference
`sdd/specs/reservations.md` and the shared policy in `domain-foundation-core.md`.
