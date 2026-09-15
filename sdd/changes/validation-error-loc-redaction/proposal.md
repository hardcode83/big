# Proposal: validation-error-loc-redaction

## Why

`_serialisable_validation_errors` (`backend/app/core/errors.py:107-117`) copies Pydantic's
`error["loc"]` into the `422` body **literally, unbounded**. Every module in this codebase
(`pricing`, `maintenance`, `cleaning`, `auth`, `access`, `reservations`, `platform`, …) declares
`model_config = ConfigDict(extra="forbid")` as a standing convention, and when that fires,
Pydantic's `error["loc"]` ends with **the literal name of the unknown key the caller sent** —
there is no schema field behind it, it is copy of raw caller input. Measured 2026-08-17 with an
authenticated probe: a 5,000-character unknown key produces a 5,182-byte body, and the result is
**identical** on `POST /api/v1/pricing-rules` and `PATCH /api/v1/incidents/{id}` — this is not a
`pricing` bug, it is the shared handler, and it reaches every module with `extra="forbid"`.

This contradicts a real requirement — «ningún mensaje de error hace eco de un valor del llamante
sin acotar» — that is **not** written in any design: it was raised by `revenue-pricing`'s security
panel of section 2 and lives only in that change's task 6.2, while D15 of that design is just the
error-code table. Whoever comes looking for this rule in `design.md` will not find it there.

**The gap predates `revenue-pricing` and is not its scope.** It lives in the shared handler
registered by `register_error_handlers` in `app/core/errors.py`, changing the `422` body touches
the published OpenAPI contract and `backend/tests/test_openapi_contract.py`, and it needs its own
panel — which is exactly why the roadmap entry exists instead of folding the fix into that change.

**Truncating `loc` blindly is the wrong fix and roadmap says so explicitly**: a validation error
of any other type (`missing`, `string_too_long`, `value_error`, …) has a `loc` made entirely of
**schema-derived** segments — field names and, for nested models or list items, several of
them — and those can legitimately be longer than a casual guess and must not be cut. The only
segment that is ever caller-controlled is the **last** one of an `extra_forbidden` error, because
that is the one Pydantic fills with the literal unknown key. Every other segment of every other
error type comes from the schema, not from the request body.

**Two frontend consumers already parse this shape** and must keep working:
`frontend/features/properties/lib/field-errors.ts` and
`frontend/features/platform/lib/field-errors.ts` both read `error.details.errors` as
`{loc: string[], type, msg}[]` and key a field-error map off `loc`'s **last segment**. Neither
maps an `extra_forbidden` error to a real form field today — an unknown key never matches an
actual field name — so bounding that segment changes nothing for the legitimate cases both files
handle; it only stops that one entry from carrying an unbounded string.

Context: `sdd/steering/security.md` (the plaintext-sink rule this gap is adjacent to, though it
does not govern this case — this is caller-echo, not persistence), `sdd/specs/api-contract.md`
(the `ErrorEnvelope`/`422` contract this change touches), `sdd/specs/revenue-pricing.md` §
Residual (where the gap was measured and pointed here), `backend/app/core/errors.py` (the shared
handler), `backend/tests/test_openapi_contract.py` (the contract test this change must keep
green).

## What changes

`_serialisable_validation_errors` bounds the **caller-controlled** segment of `loc` — the last
segment of an `extra_forbidden` error, and only that one — to a fixed maximum length, appending a
truncation marker when it cuts. Every other segment, and every `loc` of every other error type, is
left exactly as Pydantic produces it: schema-derived paths, however long, are never touched. The
fix lives once, in the shared handler, and is documented once, in `sdd/specs/api-contract.md` —
not duplicated into `revenue-pricing` or any other module's spec.

## Requirements

### R1 — The caller-controlled segment is bounded

**As a** caller of any endpoint whose schema declares `extra="forbid"`, **I want** an unknown key I
send to not be echoed back to me unbounded in the `422` body, **so that** a caller cannot use an
oversized field name to inflate the response with its own input.

Acceptance criteria:

1. WHEN a validation error's `type` is `"extra_forbidden"`, THE SYSTEM SHALL cap the **last**
   segment of its `loc` to a fixed maximum length (100 characters), replacing anything beyond that
   cutoff with a truncation marker so the response makes clear the value was cut and not merely
   short.
2. WHEN the unknown key is at or under the cap, THE SYSTEM SHALL leave it byte-for-byte unchanged
   — the cap never rewrites a value it doesn't need to.
3. THE SYSTEM SHALL apply the cap to every module with `extra="forbid"` through the one shared
   handler in `app/core/errors.py` — never per-module, never per-router.
4. WHEN a request sends a 5,000-character unknown key (the measured probe), THE SYSTEM SHALL
   produce a `422` body whose size no longer scales with the caller's input — verified with a test
   that repeats the original probe and asserts the bound holds.
5. WHEN a single request produces more than 20 `extra_forbidden` errors (a caller sending that
   many distinct unknown keys), THE SYSTEM SHALL stop adding further `extra_forbidden` entries to
   the serialised list beyond that cap and append one summary entry noting how many were omitted,
   so the `422` body's size no longer scales with the number of distinct unknown keys either —
   verified with a test that sends hundreds of distinct unknown keys and asserts the body stays
   small and bounded. Every other error type keeps being added normally: it is already bounded by
   the schema's own field count, which a caller cannot inflate.
6. WHEN the last segment of an `extra_forbidden` error's `loc` is actually truncated, THE SYSTEM
   SHALL add a sibling `"loc_truncated": true` field to that error entry, present only when
   truncation happened, so a caller-supplied key that merely ends with the truncation marker
   string (but is itself at or under the cap) is never confused for a genuinely truncated one —
   verified with a test that compares a forged key against a genuinely long one.

### R2 — Schema-derived segments are never touched

**As a** developer reading a `422` for a deeply nested schema field, **I want** every `loc`
segment that came from the schema — not from the caller — to stay intact regardless of length,
**so that** I can still tell exactly which field failed.

Acceptance criteria:

1. WHEN a validation error's `type` is anything other than `"extra_forbidden"` (`missing`,
   `string_too_long`, `value_error`, `int_parsing`, …), THE SYSTEM SHALL leave `loc` exactly as
   Pydantic produced it, unmodified, regardless of its length or number of segments.
2. WHEN a validation error's `type` is `"extra_forbidden"` and its `loc` has more than one
   segment (a nested `extra="forbid"` model), THE SYSTEM SHALL bound only the final segment and
   leave every preceding schema-derived segment unmodified.
3. THE SYSTEM SHALL cover both branches (R2.1 and R2.2) with a test each, so the distinction the
   roadmap entry calls for — caller segment vs. schema segment — is enforced and not just
   described.

### R3 — The wire shape and the published contract do not change

**As a** client parsing the `422` envelope (`frontend/lib/api/errors.ts` and its two
`field-errors.ts` consumers, and `backend/tests/test_openapi_contract.py`), **I want** `loc` to
keep the exact same shape — a JSON array of strings, in the same position of the same envelope —
**so that** existing field-error mapping and the published OpenAPI document keep working
unchanged.

Acceptance criteria:

1. THE SYSTEM SHALL keep `loc` a `list[str]` of the same length as before this change — only the
   string content of the bounded segment changes, never the type, never whether the entry is
   present.
2. THE SYSTEM SHALL keep `test_a_real_validation_failure_matches_the_published_shape` and every
   other test in `backend/tests/test_openapi_contract.py` passing unchanged: `details` is already
   published as `dict[str, Any]`, so no OpenAPI schema edit is needed or permitted for this
   change.
3. WHEN `mapPropertyFieldErrors` (`frontend/features/properties/lib/field-errors.ts`) or
   `mapFieldErrors` (`frontend/features/platform/lib/field-errors.ts`) process a `422` produced
   after this change, THE SYSTEM SHALL keep mapping every real (schema-derived) field error
   exactly as before — verified by the existing frontend tests for both modules staying green
   without modification.

### R4 — The bound is documented once, where the shared handler lives

**As a** developer who later adds a module with `extra="forbid"`, **I want** this bound documented
where the shared `422` handler is already the authority, **so that** I don't have to rediscover it
per module.

Acceptance criteria:

1. THE SYSTEM SHALL document the bound — which error `type` it applies to, the cap length, the
   entry-count cap, the `loc_truncated` signal, and the measured before/after body size for the
   original probe — in `sdd/specs/api-contract.md`'s
   section on error responses.
2. THE SYSTEM SHALL NOT introduce this requirement into `sdd/specs/revenue-pricing.md` or any
   other module spec: the gap is prior and shared, as `sdd/roadmap/validation-error-loc-redaction.md`
   states, and `revenue-pricing.md`'s residual entry is updated to point at this change instead of
   restating the gap.

## Out of scope

- **Rewriting `msg` for `extra_forbidden` errors.** Pydantic's message for that error type is a
  fixed string (`"Extra inputs are not permitted"`) that does not interpolate the caller's key —
  the only echo is in `loc`, and only there.
- **Changing the `409` duplicate-key errors** that `properties/infrastructure/repositories.py`
  raises without a `loc` at all (`sdd/specs/properties-crud.md:448`) — unrelated code path, no
  `loc` to bound.
- **A general-purpose redaction/allowlist mechanism for arbitrary error `details`.** This change
  fixes the one measured, unbounded echo; a broader mechanism is not motivated by any other
  measured gap today.

## Affected specs

- `sdd/specs/api-contract.md` — adds the bound to the section documenting `ErrorEnvelope` and the
  `422` shape (R4.1).
- `sdd/specs/revenue-pricing.md` — its residual entry for this gap is updated to point at this
  change instead of restating the open gap (R4.2).

Fuera de `sdd/specs/`, este change modifica `backend/app/core/errors.py` (implementación) y
`backend/tests/test_openapi_contract.py` u otro fichero de test nuevo bajo `backend/tests/core/`
(verificación) — no documento.
