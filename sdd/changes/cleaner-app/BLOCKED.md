# Blocked items — cleaner-app

## Host memory pressure blocks the verification fork workers

- **phase**: run → verification
- **type**: deferred (the host clears itself; no human decision needed)
- **what & why**: many other worktrees (tech-app, guest-portal-messaging,
  super-admin-identity, notification-channel-routing, autohostai, etc.) are
  simultaneously running on this host. The cleaner-app container reaches
  ~150 MB of `MemAvailable` at run time, which is below the fork-worker
  threshold vitest needs to spawn a jsdom test worker. Pure-Python / node-only
  tests (`format.test.ts`, `http-cleaner-source.test.ts`, the cycle hook test,
  `catalog-parity.test.ts`) pass cleanly; the jsdom component tests hang on
  fork-worker startup and never run. The `tsc --noEmit` process is OOM-killed
  for the same reason.
- **exact resume command**: `/sdd:review cleaner-app` runs review-panel
  verification on this host once other stacks release memory, or
  `/sdd:review cleaner-app --off-host` in CI (the GitHub Actions runner has
  the full 7 GB). The unit tests that have already run clean are evidence
  the DTOs, hooks and data source are wired correctly; the components
  follow `tech-app`'s pattern.