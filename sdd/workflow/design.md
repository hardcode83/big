# Phase: design

Write the technical design for a change. Argument: the feature name; if omitted and exactly one non-archived change exists in `sdd/changes/`, use it — otherwise ask.

## Steps

1. **Load context.** Read `sdd/project.md`, the change's `proposal.md`, and any `sdd/specs/` files it lists as affected. If there is no proposal, stop and point to the new phase.
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `design` and whose `applies_to` (if present) matches the proposal's scope. `architecture.md` and `security.md` rules are binding here — a design that needs to break one must say so explicitly as an open question, never silently.
2. **Triviality check.** If the change needs no real design decisions (obvious approach, few files, no new dependencies or data changes), say so and recommend skipping straight to the tasks phase instead of producing a ceremonial document. Only continue if the user insists or the change warrants it.
3. **Investigate the code** the change touches: current structure, patterns to follow, integration points. Design must fit the existing codebase, not an idealized one.
4. **Write** `sdd/changes/<feature>/design.md` using `sdd/workflow/templates/design-template.md`. Rules:
   - Every decision states the chosen option **and why**, with rejected alternatives one line each.
   - Reference real files/modules with paths.
   - Cover every requirement in the proposal — if a requirement has no design implication, say so explicitly.
   - Surface **open questions** rather than silently deciding on things the user should weigh in on.
   - No code beyond short illustrative snippets or interface signatures.
5. **Gate.** Summarize the key decisions and open questions, resolve the open questions with the user (offer concrete options when they are concrete choices), and wait for approval. Then suggest the tasks phase.
