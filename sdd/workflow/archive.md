# Phase: archive

Close out a completed change. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

Write spec updates in the same language as the existing specs (or the user's language for new ones).

## Steps

1. **Verify completion.** Read the change's `tasks.md`. If any task is unchecked, list them and ask the user to confirm archiving anyway (they may have been done outside the flow) — never check boxes yourself here.
   - **Steering**: if `sdd/steering/` exists, load the docs whose `phases` include `archive` and whose `applies_to` matches this change (e.g. `documentation.md`) and apply their archive-time rules/checklists before closing.
2. **Update the living specs.** For each capability the change touched (see "Affected specs" in the proposal, plus anything discovered during implementation):
   - Create or update `sdd/specs/<capability>.md` following `sdd/workflow/templates/spec-template.md`.
   - **Spec on first touch**: if the capability has no spec yet (common in projects that adopted SDD with existing code), create it covering the capability's full current behavior — the pre-existing parts this change interacted with plus what the change added — not just the delta. Don't document unrelated corners you didn't touch.
   - Specs describe the system **as it is now**, in present tense, with EARS requirements — merge the change's requirements into them, don't append a changelog.
   - Verify statements against the actual implementation, not just the proposal: the code is the source of truth for what was built.
3. **Archive.** Move `sdd/changes/<feature>/` to `sdd/changes/archive/<YYYY-MM-DD>-<feature>/` (get the date with `date +%F`). If `sdd/roadmap.md` has an entry for this change, check it off `[x]`.
4. **Summarize.** List the spec files created/updated and confirm the archive location. If the project uses git, suggest committing specs + archive together with the implementation.
