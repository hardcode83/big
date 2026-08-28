# Blocked: blocked-transitions-web

## 1. D3 exhaustiveness guard covers triggers only

- **phase**: review
- **type**: deferred
- **what & why**: `frontend/features/dashboard/stalls/lib/action-map.ts:90-96` adds the
  `Exclude<…, never>` guard only on the `ClockTrigger` axis; a new `PropertyOperationalState`
  silently maps to `null` instead of failing the typecheck. The JSDoc on `:86-88` documents that
  the guard is partial and why (`null` is a legitimate answer for a state that admits no action,
  so the states axis cannot be closed the same way). It is a long-tail drift risk, not a defect
  today: every state that exists is covered by the cartesian-product test in `action-map.test.ts`.
- **resume command**: optional follow-up; fold into the next change that touches the matrix, or
  `/sdd:run` for a small dedicated change if the states axis ever needs to be closed.
