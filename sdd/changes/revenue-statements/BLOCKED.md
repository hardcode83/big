# BLOCKED — revenue-statements

## 2026-08-30 — §11.2 global baseline and Pyright environment

The exact `uv run` commands cannot find either tool because `backend/pyproject.toml`
does not declare them. Using the temporary container-only `uvx` mechanism, Ruff can be
run for a baseline comparison, but Pyright cannot start:

- `docker compose -f docker-compose.yml -f docker-compose.worktree.yml run --rm backend uv run ruff check backend/`
  fails before analysis with `Failed to spawn: ruff (No such file or directory)`.
- `docker compose -f docker-compose.yml -f docker-compose.worktree.yml run --rm backend uv run pyright backend/`
  fails before analysis with `Failed to spawn: pyright (No such file or directory)`.

§11.1 is verified independently: `9225 passed, 41 skipped`.

## 2026-08-30 — remaining verification evidence unavailable

- Equivalent Ruff execution via `uvx` reports `1263` findings globally versus `1266` on
  `origin/main`; the final `app/statements`/`tests/statements` check reports only the six
  findings already present in the baseline, and zero findings on the current feature diff.
- Equivalent Pyright execution via `uvx` downloaded the tool but could not start its
  bundled Node runtime because the image lacks `libatomic.so.1`.
- 11.3 is resolved: `make bootstrap` and `make seed-demo` passed with the demo seed
  evidence recorded in the session (2 users, 2 properties, 3 guests, 3 reservations,
  1 checklist template, 1 cleaning task, 6 cleaning photos, 3 incidents, 1 conversation,
  and 2 messages).
- 11.4 is explicitly deferred to `PR_OPEN`: `gh pr checks` cannot run before `/sdd:ship`
  creates the Pull Request (`no pull requests found for branch`); this is no longer a
  `/sdd:run` blocker.

Resume command after supplying the environment and opening the PR:
`/sdd:run revenue-statements 11`
