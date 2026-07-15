# Phase: new

Create a change proposal. Argument: the feature name — normalize to kebab-case (e.g. `user-auth`). If no argument was given: if `sdd/roadmap.md` exists, propose taking its first unchecked entry; otherwise derive a short name from the user's description and confirm it.

## Steps

1. **Load context.** Read `sdd/project.md` and skim `sdd/specs/` for capabilities this change touches. If `sdd/` doesn't exist, tell the user to run the init phase first and stop.
   - **Steering**: if `sdd/steering/` exists, read each doc's frontmatter and fully load those whose `phases` (if present) include `new` and whose `applies_to` (if present) matches the areas the request describes. A proposal must respect `product.md` principles when that doc exists — if the request conflicts with them, raise it before writing.
   - **Roadmap**: if the feature comes from `sdd/roadmap.md`, use its line (and source reference) as the seed, and mark the entry as started by appending ` → changes/<feature>/`.
2. **Understand the ask.** If the request is ambiguous on something that changes the requirements (not implementation details), ask the user 1-3 targeted questions. Otherwise proceed.
   - **Adopting in-flight work**: if the feature is already partially built (the user says so, or the code clearly shows it), the proposal documents the *intended end state* as usual — reality is captured later, when the tasks phase pre-checks what's already done.
3. **Write** `sdd/changes/<feature>/proposal.md` using `sdd/workflow/templates/proposal-template.md`. Rules:
   - Requirements are user stories with **EARS acceptance criteria** ("WHEN <trigger>, THE SYSTEM SHALL <response>"; also WHILE/WHERE/IF-THEN as needed). Each criterion must be objectively verifiable.
   - Number requirements (R1, R2…) — tasks will reference them later.
   - 3-7 requirements for a typical change. If you need more, the change is too big: propose splitting it.
   - An explicit **Out of scope** section — this is what keeps changes small.
   - In **Affected specs**, list the `sdd/specs/` files this change will touch. Flag the ones that don't exist yet with *(no existe aún — se creará al archivar)* — that's expected in adopted/brownfield projects, not a blocker.
   - Do NOT create `design.md` or `tasks.md`, and do not write any code.
4. **Gate.** Present a short summary and ask the user to review. On approval, suggest the next step: the design phase — or the tasks phase directly if the change is trivial (no new architecture, few files, obvious approach).
