# Phase: review

Two modes, chosen by argument:

- no argument — **drift check**: compare `sdd/specs/` against the codebase.
- `<feature>` — **change review**: verify the implementation of `sdd/changes/<feature>/` against its proposal.

## Drift check

1. Read `sdd/project.md` and every file in `sdd/specs/`.
2. For each spec requirement, verify the code still behaves that way (read the relevant code; run tests only if cheap).
3. Report a findings list, most severe first:
   - **Broken**: spec says X, code does Y.
   - **Undocumented**: significant behavior with no spec coverage.
   - **Stale**: spec references removed code/features.
4. Offer to update the affected spec files (with user approval, one file at a time).

## Change review

1. Read the change's `proposal.md`, `design.md` (if any), and `tasks.md`.
2. For each EARS requirement in the proposal, find the implementing code and its test. Mark it **met / partially met / unmet**, with file references.
3. Flag scope creep: implemented behavior not covered by any requirement.
4. Conclude with a verdict: ready to archive, or list what's missing.

Do not fix anything in either mode — report only, and let the user decide.
