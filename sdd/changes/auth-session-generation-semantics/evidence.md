# Run evidence — auth-session-generation-semantics

**Run date**: 2026-09-04
**Branch**: sdd/auth-session-generation-semantics
**Implementation SHA**: 309e3753fda90922d76b2361d01151f55c4a51c4

## Suite totals (this run)
- Files: 205 (204 passed, 1 failed)
- Tests: 2122 (2121 passed, 1 failed)
- Command: `cd frontend && npm test`

## Suite totals (notifications-inbox-web, reference)
- Source: `sdd/changes/archive/2026-08-29-notifications-inbox-web/tasks.md` §11 (no `evidence.md` exists in the archive — the post-completion totals are recorded inline as 166/1628 with `--maxWorkers=1`).
- Files: 166 (all passed)
- Tests: 1628 (all passed, 0 skipped)

## Delta
- Files: +39 (205 − 166)
- Tests: +494 (2122 − 1628)
- Interpretation: the suite has grown since `notifications-inbox-web` shipped 2026-08-29 (other features added tests in the intervening weeks). This change adds 4 tests in `session-cache-purge.test.ts` (R1.1, R1.2, R1.4, R4.1) and 2 new interleaving tests + 1 companion + 1 mutation regression in the in-scope files — counted below.

## Suite breakdown (in-scope)
- `lib/auth/session-store.test.ts`: PASS (3 tests)
- `lib/auth/refresh-coordinator.test.ts`: PASS (4 tests) — note: the 5.6 substitution of `purgeSessionCache()` then `clearSessionTokens()` (instead of `clearSessionTokens()` alone) keeps the rejection + tokens-null assertions green after D3.
- `lib/auth/session-cache-purge.test.ts`: PASS (4 tests, NEW — R1.1, R1.2, R1.4, R4.1)
- `lib/auth/auth-provider.test.tsx`: PASS (17 tests — all interleaving tests green; the rewritten test 4 + companion cover D5 in both tokens-live and tokens-null paths)
- `features/notifications/hooks/use-mark-read.test.tsx`: PASS (15 tests — R4.4 verified: the `vi.mock` proxies `getSessionGeneration` to the real implementation in `session-store.ts`; verified the fails-when-R1-reverted property during the 5.x fix round)

## Rule 11 ownership guard
- PASS — `make check-rule11-ownership` (host, no stack): `veredicto: ningún bloque fuera de la tabla de la regla 11 declara quién escribe un sumidero del censo`. 106 markdown files walked, 888 python files walked. The new prose in `sdd/specs/frontend-auth-session.md` (section 3) cites `setSessionTokens` and `purgeSessionCache()` as the two writers of `sessionGeneration` and names `use-mark-read.ts` / `use-mark-all-read.ts` as the consumers — all inside the census.

## openapi.json
- Unchanged — `git status frontend/openapi.json` → "nothing to commit, working tree clean". The run did not touch the API contract (no schema changes were in scope).

## Environment noise
- `frontend/test/color-tokens.test.ts > colour tokens > scans a tree that is actually there, so a broken walk cannot pass empty`: 1 failure. Cause: the test asserts `next-env.d.ts` is present in the `frontend/` root, but the file is missing in this worktree (Next.js generates it on first `next dev`/build). This is environment noise — unrelated to the auth-session change. The test's own purpose is to verify the tree walk, so the missing auto-generated artefact is exactly the kind of bootstrap gap `sdd/project.md` §«Worktree bootstrap» warns about. No regression: every other test in the suite passes, including all in-scope auth + use-mark-read tests.

## Notes
- The two ENOENT files named in `sdd/project.md` (`features/provenance/workflow-contract.test.ts` and `lib/config/build-identity-contract.test.ts`) did not surface as errors in this run — the suite completed with the colour-tokens failure as the only red.