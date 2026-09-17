# Tasks: validation-error-loc-redaction

## 1. Bound the caller-controlled `loc` segment <!-- panel: PASS 2026-09-15 receipt:05b73c22 -->

- [x] 1.1 In `backend/app/core/errors.py`, add a module-level cap (e.g.
      `_EXTRA_FORBIDDEN_LOC_MAX_LENGTH = 100`) and a truncation marker constant, and change
      `_serialisable_validation_errors` so that, WHEN `error.get("type") == "extra_forbidden"`,
      the **last** element of the `loc` list is capped to that length (appending the marker when
      cut) — every other segment of that `loc`, and the whole `loc` of every other error `type`,
      is left exactly as Pydantic produced it. [R1.1, R1.2, R1.3, R2.1, R2.2, R3.1]
- [x] 1.2 New file `backend/tests/core/test_errors.py`. Cover, against a real
      `RequestValidationError` raised by a throwaway `extra="forbid"` model (not a hand-built
      dict — the fix has to survive Pydantic's actual error shape):
      - An unknown key of 5,000 characters (the original probe) produces a `loc` last segment
        capped to the constant, with the marker appended, and the resulting `422` body no longer
        scales with input size. [R1.1, R1.4]
      - An unknown key at or under the cap is returned byte-for-byte unchanged (no marker
        appended). [R1.2]
      - A non-`extra_forbidden` error (e.g. `missing` on a required field, or `string_too_long`)
        keeps its `loc` completely unmodified, including when a segment is unusually long by
        construction. [R2.1]
      - A nested `extra="forbid"` model (an unknown key under a nested object field) caps only
        the final segment; the schema-derived segments before it are untouched. [R2.2]
      - `loc` stays a `list[str]` of the same length before and after truncation (no entry
        dropped, no type change). [R3.1]
      [R1, R2, R3.1]

## 2. Update the documented contract <!-- panel: skipped — docs-only section (sdd/specs/ prose edits, no production code) -->

- [x] 2.1 `sdd/specs/api-contract.md`, section "Lo que el documento declara sobre los errores":
      add a bullet documenting the bound — which error `type` it applies to
      (`extra_forbidden`), the cap length, that every other segment/type is untouched, and the
      measured before/after body size for the original probe (5,182 bytes → bounded). [R4.1]
- [x] 2.2 `sdd/specs/revenue-pricing.md`, the residual bullet "El `422` de validación devuelve el
      `loc` de Pydantic sin acotar…": update it to say the gap is fixed by this change (name it),
      pointing at `sdd/specs/api-contract.md` for the actual contract — do not restate the fix
      here. [R4.2]

## 3. Verification <!-- panel: skipped — verification-only section, no production code -->

- [x] 3.1 Backend test suite passes: `docker compose exec backend uv run pytest` (stack up via
      `make up` first; `docker compose run --rm backend uv run pytest` if the stack is down).
      Confirms `test_openapi_contract.py` (R3.2) and the new `test_errors.py` (section 1) are
      green together with the rest of the suite. A single unscoped run was repeatedly killed by
      host-wide memory contention from concurrent peer-session worktree stacks (exit 137 twice,
      then the harness itself stopped the process for low memory) — not a regression. Verified
      instead by running the suite chunked by `tests/<module>` (24 module dirs + root-level
      files, sequential, one `docker compose exec` per chunk to bound peak memory): **all chunks
      passed** except `tests/maintenance` (898 passed, 2 failed —
      `test_report_incident_from_conversation.py::test_the_audit_row_carries_no_word_the_guest_typed`
      and `::test_the_guest_branch_leaks_no_word_the_guest_typed_either`, confirmed unrelated:
      neither references `app/core/errors.py`, `loc`, or any symbol this change touches, and
      `git log` shows the file was last touched by unrelated `messaging`/`guest-portal` features
      — pre-existing, not introduced here). Root-level chunk (includes `test_errors.py` and
      `test_openapi_contract.py`): 2330 passed, 0 failed.
- [x] 3.2 Backend static tooling: from `backend`, `uv sync --frozen` then `uv run pyright .` —
      no new findings introduced by section 1. (962 pre-existing findings elsewhere in the
      repo, none in `backend/app/core/errors.py` or `backend/tests/core/test_errors.py`,
      confirmed by grep.)
- [x] 3.3 `make check-rule11-ownership` (host, no Docker) — this change edits prose under `sdd/`
      and a docstring-adjacent constant in `backend/app/core/errors.py`; confirms neither trips
      the rule-11 ownership guard. Verdict: "ningún bloque fuera de la tabla de la regla 11
      declara quién escribe un sumidero del censo".
- [x] 3.4 Frontend field-error mapping stays green without any frontend source change:
      `docker compose exec frontend npm test -- features/properties/lib/field-errors.test.ts
      features/platform/lib/field-errors.test.ts` (vitest, scoped to these two files — avoids the
      unrelated worktree `ENOENT` files a full `npm test` would hit per `sdd/project.md`) — R3.3,
      run to confirm no regression, not because either file changes. Result: 2 files, 11 tests,
      all passed.

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- Section 1 (2026-09-15): constant is `_EXTRA_FORBIDDEN_LOC_MAX_LENGTH = 100` in
  `backend/app/core/errors.py`, meaning the capped segment's TOTAL length (including the
  marker) is 100, not 100 + marker.
- Truncation marker: `_EXTRA_FORBIDDEN_LOC_TRUNCATION_MARKER = "...(truncated)"` (15
  chars), appended after slicing the segment to `100 - len(marker)` characters.
- Only `error.get("type") == "extra_forbidden"` is touched; the cap applies to `loc[-1]`
  only (nested models keep every preceding schema-derived segment untouched).
- Measured with a throwaway `extra="forbid"` FastAPI model + `httpx.ASGITransport` (same
  pattern as `test_openapi_contract.py`): a 5,000-char unknown key now produces a 282-byte
  `422` body (vs. the 5,182-byte body measured pre-fix for the same probe in the
  proposal). Body size no longer scales with the caller's key length.
- Test file: `backend/tests/core/test_errors.py` (6 tests, all passing). Uses two
  throwaway models, `_LeafModel` (top-level `extra="forbid"`) and `_NestedModel` (wraps
  `_LeafModel`), both mounted on a local `FastAPI()` app via `register_error_handlers`.
- Verification run: `docker compose exec backend uv run pytest tests/core/test_errors.py
  tests/test_openapi_contract.py -q` → `21 passed` (6 new + 15 pre-existing in
  `test_openapi_contract.py`). Note: inside the backend container the working directory
  is `/app` and paths are relative to `backend/` (i.e. `tests/...`, not
  `backend/tests/...`) — the task's verification command as literally written
  (`backend/tests/core/test_errors.py`) 404s inside the container; drop the `backend/`
  prefix when running it there.
- Section 2 (2026-09-15): added one bullet to `sdd/specs/api-contract.md`'s "Lo que el
  documento declara sobre los errores" (after the `content` exemption bullet, before
  "### Verificación estructural sin vacuidad") documenting the `extra_forbidden`-only,
  100-char-total cap and the 5,182 → 282 byte measurement, citing
  `validation-error-loc-redaction`. Rewrote `sdd/specs/revenue-pricing.md`'s residual
  bullet (Residual section, "El `422` de validación devolvía...") to past tense, stated
  the gap is closed by `validation-error-loc-redaction`, and pointed at
  `sdd/specs/api-contract.md` for the mechanism instead of restating it.
- Round 1 review fix (2026-09-15), `sdd-security` findings: (1) HIGH — the response could
  still scale on error-COUNT (many distinct unknown keys); added
  `_MAX_EXTRA_FORBIDDEN_ERRORS = 20` in `backend/app/core/errors.py`, after which further
  `extra_forbidden` entries are dropped and one summary entry (`type:
  "extra_forbidden_omitted"`) is appended noting how many. Removed the now-false "number
  of errors is out of scope" bullet from `proposal.md`'s Out of scope section and added
  R1.5 instead. (2) MEDIUM — softened the "every other segment is schema-derived" claim to
  name the `dict[str, <model>]` exception, in both `sdd/specs/api-contract.md` and the code
  comment above `_serialisable_validation_errors`; no code change (no such field exists
  today). (3) LOW — the truncation marker suffix was forgeable by a caller-chosen key at or
  under the cap; added a sibling `"loc_truncated": true` field, set only when truncation
  actually happened (additive — both `field-errors.ts` consumers only read `loc`/`type`/
  `msg` and ignore unknown keys). New R1.6. Tests added to `test_errors.py`: entry-count
  cap (300 distinct unknown keys, body stays < 3000 bytes) and forged-vs-genuine truncation
  marker distinguishability. All 6 pre-existing tests kept passing unmodified.
- Round 2 review fix (2026-09-15), `sdd-security` HIGH + `sdd-qa` LOW: round 1's count cap
  was scoped to `extra_forbidden`, leaving the COUNT axis open for every other type (the
  panel measured a 1 MiB body producing a 52.89 MiB `422` with 520,000 `dict_type` entries
  against the pricing `list[dict[str, Any]]` fields, which have no `max_length`).
  Generalised it in `backend/app/core/errors.py`: `_MAX_EXTRA_FORBIDDEN_ERRORS` →
  `_MAX_SERIALISED_ERRORS = 20`, now a cap on the TOTAL entries of any `type`, applied by
  slicing `exc.errors()` before the serialisation loop (simpler than threading a counter,
  and it no longer serialises what it drops); summary entry renamed
  `extra_forbidden_omitted` → `errors_omitted` because the omitted entries are no longer
  necessarily `extra_forbidden`. The `loc` segment cap and `loc_truncated` are untouched and
  still apply to every serialised `extra_forbidden` entry. Fix is in the shared handler only
  — no `max_length` added to the pricing schemas (per `## Out of scope`). Measured ordering
  gotcha: Pydantic reports declared-field violations BEFORE `extra_forbidden`, so a genuine
  `missing` survives the total cap (new R1.7 makes that a requirement instead of an
  accident). Rewrote R1.5 (dropped the false "bounded by the schema's own field count"
  justification) and the `sdd/specs/api-contract.md` bullet. Tests: 2 new
  (`test_a_genuine_error_survives_alongside_capped_unknown_keys`, 30 unknown keys + missing
  field → 1 `missing` + 19 `extra_forbidden` + summary; and
  `test_many_errors_of_a_non_extra_forbidden_type_do_not_scale_the_response`, a throwaway
  `list[dict[str, Any]]` model with 80 invalid items → 20 `dict_type` + summary, body <
  3000 bytes), 1 updated for the renamed constant/summary type. Verification run: `docker
  compose exec backend uv run pytest tests/core/test_errors.py tests/test_openapi_contract.py
  -q` → `25 passed` (10 in `test_errors.py` + 15 pre-existing).
