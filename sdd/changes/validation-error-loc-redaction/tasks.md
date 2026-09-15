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

## 3. Verification

- [ ] 3.1 Backend test suite passes: `docker compose exec backend uv run pytest` (stack up via
      `make up` first; `docker compose run --rm backend uv run pytest` if the stack is down).
      Confirms `test_openapi_contract.py` (R3.2) and the new `test_errors.py` (section 1) are
      green together with the rest of the suite.
- [ ] 3.2 Backend static tooling: from `backend`, `uv sync --frozen` then `uv run pyright .` —
      no new findings introduced by section 1.
- [ ] 3.3 `make check-rule11-ownership` (host, no Docker) — this change edits prose under `sdd/`
      and a docstring-adjacent constant in `backend/app/core/errors.py`; confirms neither trips
      the rule-11 ownership guard.
- [ ] 3.4 Frontend field-error mapping stays green without any frontend source change:
      `docker compose exec frontend npm test -- features/properties/lib/field-errors.test.ts
      features/platform/lib/field-errors.test.ts` (vitest, scoped to these two files — avoids the
      unrelated worktree `ENOENT` files a full `npm test` would hit per `sdd/project.md`) — R3.3,
      run to confirm no regression, not because either file changes.

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
