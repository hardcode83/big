# Blocked: blocked-transitions-web

## 1. R5.1 in-card link missing (R5.1 violation)

- **phase**: review
- **type**: decision
- **what & why**: Proposal R5.1 mandates "SHALL enlazarlo desde la pantalla con un texto breve que no ocupe más de una línea." The card renders `card.blocked.window` as a plain `<p>` at `frontend/features/dashboard/stalls/components/blocked-transitions-section.tsx:139-141` with no anchor to `docs/properties.md#aviso-de-desajustes-en-la-card-del-dashboard`. R5.1 is therefore not met. Flagged by `sdd-review-documentation` F3 and `sdd-qa` F2.
- **resume command**: `/sdd:review blocked-transitions-web` after the wrap-to-link fix lands (one-line `<a href="/docs/properties#aviso-de-desajustes-en-la-card-del-dashboard">` or `next/link`).

## 2. README + docs/dashboard.md claim dashboard is read-only (documentation drift)

- **phase**: review
- **type**: decision
- **what & why**: README.md:21 and docs/dashboard.md:14 explicitly state the dashboard has no write actions and that `resolve` is "fuera de alcance desde la web". The implementation just wired both `cancel-cleaning` and `resolve-incident` into the dashboard card for `PROPERTY_MANAGER`. Drift introduced by the change. Flagged by `sdd-review-documentation` F1 and F2; `steering/documentation.md` "README al día por change" + "docs/<capability>.md al archivar".
- **resume command**: `/sdd:review blocked-transitions-web` after the README and `docs/dashboard.md` updates land.

## 3. R5.3 stalls-query 5xx state is silent (R5.3 partial)

- **phase**: review
- **type**: decision
- **what & why**: When `useBlockedTransitions` fails with 5xx, `dashboard-view.tsx:55-57` substitutes an empty map and the section silently disappears. Proposal R5.3 says "SHALL mostrar el estado de error localizado del contrato común y SHALL no ocultar la card". Locale key `card.blocked.error.fetch` exists in both ES/EN but is unused. Flagged by `sdd-qa` F1 and `sdd-review-i18n` Observation 1.
- **resume command**: `/sdd:review blocked-transitions-web` after the section renders `t("card.blocked.error.fetch")` on `stallsQuery.isError`.

## 4. R3.4 409-specific locale message unused

- **phase**: review
- **type**: decision
- **what & why**: Locale key `card.blocked.error.conflict` is defined in both ES and EN but neither dialog branches on `mutation.error?.status === 409` — both flatten to `error.generic`. Proposal R3.4: "SHALL mostrar el motivo al usuario". Flagged by `sdd-security` Finding 1.
- **resume command**: `/sdd:review blocked-transitions-web` after the dialogs branch on status.

## 5. R3.3 dialog error-rendering has no test (test coverage gap)

- **phase**: review
- **type**: decision
- **what & why**: The hook-level invalidation on error is tested (`use-cancel-cleaning-task.test.tsx:90-113`, `use-resolve-incident.test.tsx:116-138`), but neither `cancel-cleaning-dialog.test.tsx` nor `resolve-incident-dialog.test.tsx` exercises the `mutation.isError` → `error.generic` rendering path. A future change that closes the dialog on `onError` would not be caught. Flagged by `sdd-architect` F4 and `sdd-qa` F3.
- **resume command**: `/sdd:review blocked-transitions-web` after the dialog tests are extended.

## 6. D5 design contradiction: hook location

- **phase**: review
- **type**: decision
- **what & why**: Design D5 first sentence says the hooks live in `frontend/features/dashboard/stalls/hooks/`, but they ship in `features/cleaning/hooks/` and `features/incidents/hooks/`. tasks.md 5.1/5.2 agree with the implementation. The design text is what is wrong, not the code. Flagged by `sdd-architect` F1.
- **resume command**: amend D5 first sentence in `sdd/changes/blocked-transitions-web/design.md` (owner decides whether to amend design or move code; the second sentence of D5 already justifies the cross-feature layout).

## 7. D3 exhaustiveness guard covers triggers only

- **phase**: review
- **type**: deferred
- **what & why**: `action-map.ts:90-96` adds the `Exclude<…, never>` guard only on the `ClockTrigger` axis; a new `PropertyOperationalState` silently maps to `null`. The JSDoc on `:86-88` documents the partial guard. Adds a long-tail drift risk; not a blocker today. Flagged by `sdd-architect` F2.
- **resume command**: optional follow-up; `/sdd:run` for a small change if pursued, or fold into the next change that touches the matrix.

## 8. D9 barrel over-exports dialogs and types

- **phase**: review
- **type**: deferred
- **what & why**: `frontend/features/dashboard/stalls/index.ts:11-20` exports `CancelCleaningDialog`, `ResolveIncidentDialog`, `stallsKeys`, `ActionKind`, `ClockTrigger`, `BlockedTransitionSummary`, `BlockedTransitionPage` — D9 listed only `useBlockedTransitions`, `BlockedTransitionsSection`, `actionMapFor`. The dialogs are imported internally by `blocked-transitions-section.tsx`, so re-exporting widens the public surface slightly. Flagged by `sdd-architect` F3.
- **resume command**: optional follow-up; one-line barrel edit.

## 9. Pre-existing test infra failures (NOT this change)

- **phase**: review
- **type**: deferred
- **what & why**: 5 test files (`features/auth/auth-session.integration.test.tsx`, `user-menu.test.tsx`, `field-public-guest-shell.test.tsx`, `workspace-shell.test.tsx`, `app/route-wiring.test.tsx`) fail to import `@radix-ui/react-alert-dialog` — declared in `frontend/package.json:18` but not present in the `node_modules` volume in this worktree (added by `2de5608 feat(public-zone): harden public zone UX after first deploy`). The change-specific suite (89 tests across 9 files in `dashboard/stalls`, `cleaning/hooks/use-cancel-cleaning-task`, `incidents/hooks/use-resolve-incident`, `lib/auth/permissions`) all passes. Pre-existing, not in diff. Flagged by `sdd-qa` "Test execution" section.
- **resume command**: `docker compose exec frontend npm install` (or `make up`) to materialize the missing dep. Out of this change's scope.
