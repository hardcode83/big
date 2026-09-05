# Run evidence — auth-session-generation-semantics

**Run date**: 2026-09-04
**Branch**: sdd/auth-session-generation-semantics
**Implementation SHA**: e16bcc94 (rounds 1-2 committed at 97bbc93d; round 3 / D8-R6, the two-counter split, at ba6199b6; round 4 — the stalls client wiring fix, `refresh()`'s guard, and the deferred-rotation-invalidation writeup — at e16bcc94, after the fourth `/sdd:review` panel's security finding)

## Suite totals (this run)
- Files: 207 (206 passed, 1 failed — `topbar-overflow.browser.test.tsx`, a pre-existing browser-mode import flake unrelated to this change)
- Tests: 2131 (2131 passed, 0 failed)
- Command: `cd frontend && npm test`

## Suite totals (notifications-inbox-web, reference)
- Source: `sdd/changes/archive/2026-08-29-notifications-inbox-web/tasks.md` §11 (no `evidence.md` exists in the archive — the post-completion totals are recorded inline as 166/1628 with `--maxWorkers=1`).
- Files: 166 (all passed)
- Tests: 1628 (all passed, 0 skipped)

## Delta
- Files: +41 (207 − 166)
- Tests: +503 (2131 − 1628)
- Interpretation: the suite has grown since `notifications-inbox-web` shipped 2026-08-29 (other features added tests in the intervening weeks). This change adds tests across four fix rounds — counted per file below.

## Suite breakdown (in-scope)
- `lib/auth/session-store.test.ts`: PASS (4 tests — round 3/D8 added a test confirming `tokenGeneration` moves on a token write/clear but not on a bare cache purge)
- `lib/auth/session-cache-purge.test.ts`: PASS (5 tests — round 2 fix round rewired the mock and added a test that populates the mocked `QueryClient` then asserts it's empty after `purgeSessionCache()`)
- `lib/auth/refresh-coordinator.test.ts`: PASS (7 tests) — note: the 5.6 substitution of `purgeSessionCache()` then `clearSessionTokens()` (instead of `clearSessionTokens()` alone) keeps the rejection + tokens-null assertions green after D3. Round 3/D8 added three tests reproducing the exact security-review interleaving: a legitimate rotation is not discarded, a genuinely revoked session is still cleared, and the coordinator's own guard now advances `sessionGeneration` on its own.
- `lib/auth/auth-provider.test.tsx`: PASS (19 tests — round 2/D7 added a regression test that a stale in-flight refresh cannot resurrect tokens after a failed login; round 4 added a second regression test that `refresh()`'s own catch cannot clobber a winning login's session).
- `lib/api/authenticated-client.test.ts`: PASS (2 tests, NEW in round 2/D7 — exercises the real composed `onUnauthorized` path, not the listener in isolation)
- `features/notifications/hooks/use-mark-read.test.tsx`: PASS (15 tests — R4.4 verified: the `vi.mock` proxies `getSessionGeneration` to the real implementation in `session-store.ts`; verified the fails-when-R1-reverted property during the 5.x fix round; `use-mark-all-read`'s tests live in this same file, there is no separate `use-mark-all-read.test.tsx`)
- `lib/api/client.test.ts`: PASS (19 tests, pre-existing/unmodified — re-verified as part of the `authenticated-client.ts` dependency chain, not new coverage)
- `features/dashboard/stalls/**` (7 test files, 86 tests): PASS, unaffected by round 4's one-line `onSessionExpired` wiring fix in `data/index.ts` — re-verified after the fix, no regressions.

## Rule 11 ownership guard
- PASS — `make check-rule11-ownership` (host, no stack): `veredicto: ningún bloque fuera de la tabla de la regla 11 declara quién escribe un sumidero del censo`. 106 markdown files walked, 888 python files walked. The new prose in `sdd/specs/frontend-auth-session.md` (section 3) cites `setSessionTokens` and `purgeSessionCache()` as the two writers of `sessionGeneration` and names `use-mark-read.ts` / `use-mark-all-read.ts` as the consumers — all inside the census.

## openapi.json
- Unchanged — `git status frontend/openapi.json` → "nothing to commit, working tree clean". The run did not touch the API contract (no schema changes were in scope).

## Environment noise
- `features/shell/components/topbar-overflow.browser.test.tsx`: fails to import in browser (chromium) mode — `TypeError: Failed to fetch dynamically imported module`. Reproduces in isolation the same way; unrelated to `lib/auth`/`lib/api` (shell/topbar feature, CSS import resolution in browser mode). Not a regression from this change.
- `frontend/test/color-tokens.test.ts`'s `next-env.d.ts`-presence check (previously red in this worktree due to the missing auto-generated Next.js artefact — see `sdd/project.md` §«Worktree bootstrap») is green in this run's totals above; the artefact bootstrap gap appears intermittent across worktree recreations, not tied to this change either way.

## Notes
- The two ENOENT files named in `sdd/project.md` (`features/provenance/workflow-contract.test.ts` and `lib/config/build-identity-contract.test.ts`) did not surface as errors in this run — the suite completed with the colour-tokens failure as the only red.