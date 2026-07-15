# Phase: init

Bootstrap SDD in the current project. Optional argument: path to an initial
planning document (markdown) — used to seed steering docs and the roadmap.

## Steps

### 1. Check existing state

If `sdd/project.md` exists and is already filled in (no placeholder comments), ask the user which parts to re-run: regenerate steering, re-run the extras step (MCPs/models/pointers), add a spec baseline, or ingest a planning document. Skip everything else.

### 2. Analyze inputs

**The repository.** Explore the codebase to determine:

- What the project is (read README, package manifests).
- Stack: languages, frameworks, versions, infra (Dockerfiles, terraform, CI config).
- Components present: frontend, backend, infra, CLI, etc. — this drives which steering docs and MCPs to offer.
- Exact commands for build, test, lint, and running locally (from package.json scripts, Makefile, justfile, CI workflows). Verify they exist; never invent commands.
- Conventions: folder structure, notable patterns, existing agent-rules files (CLAUDE.md, AGENTS.md).
- Which agent tools have SDD shims installed (`.claude/skills/sdd-*`, `.opencode/command/sdd-*.md`) — the extras step targets those.

Keep exploration proportional — this is a steering summary, not an audit.

**The planning document** (if one was passed as argument). Read it and triage its content into three buckets, then confirm the triage with the user before writing anything:

| Content | Destination |
|---|---|
| Vision, target users, principles, goals | `sdd/steering/product.md` |
| Stack/architecture decisions already made | `sdd/project.md` + `sdd/steering/architecture.md` |
| Feature list / phases / milestones | `sdd/roadmap.md` — one line per future change, in order |

Do NOT turn the plan's features into proposals now — proposals are written just-in-time by the `new` phase, one at a time, when their turn comes.

**Re-ingesting an updated plan** (project already initialized): merge, never regenerate. Diff the plan against the current `sdd/roadmap.md` and steering, then:

- Checked (`[x]`) and in-progress (`→ changes/…`) entries are history — never rewrite or reorder them.
- New features → new `- [ ]` entries, inserted where they belong in the order.
- Dropped features → remove their pending entries (confirm first).
- Changed features not yet started → edit their pending line.
- Changes that contradict behavior already built (there's a spec in `sdd/specs/` for it) → don't just edit the roadmap: flag them explicitly as `/sdd-new` candidates, because reality now disagrees with the plan.
- Vision/architecture deltas → update the affected steering docs, showing the user the diff.

### 3. Write the core scaffold

Create if missing: `sdd/specs/` and `sdd/changes/archive/`.

Write `sdd/project.md` with sections: **Overview**, **Stack**, **Commands** (exact, copy-pasteable), **Conventions**, **Context** (links, enabled MCPs/model profile). Keep it under ~80 lines — it gets read at the start of every SDD phase.

If a planning doc provided a feature list, write `sdd/roadmap.md` from `sdd/workflow/templates/roadmap-template.md`.

### 4. Steering docs

Read `sdd/workflow/references/steering.md` for the format and loading rules. Ask the user (multi-choice) which docs to create — tailor the component/language options to what step 2 detected:

- `product.md` — vision and principles. Seed from the planning doc if there is one; otherwise **interview the user briefly** (2-3 questions: what are we building, for whom, non-negotiable principles) — the vision is the one thing not derivable from code.
- `architecture.md` — architecture rules and standing decisions.
- `security.md` — security requirements and checklists.
- `testing.md` — test types and when, conventions, quality bars. Seed from the test setup actually present (frameworks, fixtures, CI gates).
- `documentation.md` — which docs must stay updated per change (API spec, runbooks, ADRs). Only what `sdd/specs/` doesn't already cover.
- Per-component docs (`frontend.md`, `backend.md`, `infra.md`, …) and/or per-language docs (`python.md`, `typescript.md`, …) — generate from the conventions actually observed in that part of the codebase.

Create the chosen ones in `sdd/steering/` from `sdd/workflow/templates/steering/`, filling them with real content (repo analysis, planning doc, interview) — never leave placeholder-only files. Give each a correct frontmatter (`applies_to`, `phases`) per the reference doc.

Also offer: nested agent-rules files per component directory (CLAUDE.md for Claude Code, AGENTS.md for most other tools) for short always-on rules that apply even outside the SDD flow. If accepted, keep them to ~10 lines each and don't duplicate steering content — link to the steering doc instead.

### 5. Spec baseline (existing codebases)

If step 2 found significant existing functionality and `sdd/specs/` is empty, offer a baseline:

1. Propose the list of capabilities detected in the code (e.g. auth, billing, report-export).
2. Let the user pick the 3-6 **core** ones (multi-choice). Recommend against a full backfill — speculative specs nobody audits are worse than no specs.
3. For each chosen capability, read the actual implementation and write `sdd/specs/<capability>.md` describing **current real behavior** (present tense, EARS), using `sdd/workflow/templates/spec-template.md`.

Tell the user the rest is covered lazily: when a change touches an undocumented area, the `archive` phase creates its spec ("spec on first touch").

### 6. Offer optional extras

Read `sdd/workflow/references/mcp-catalog.md`. When re-running this step on an already-initialized project, first diff against what's already enabled (the **Context** section of `sdd/project.md` plus the actual config files) and offer only what's new or missing — highlight catalog entries that didn't exist when the project was last initialized. Ask the user about:

1. **MCPs** (multi-choice) — only the catalog entries relevant to the detected stack (e.g. don't offer Postgres to a project with no database).
2. **LSPs** (multi-choice) — read `sdd/workflow/references/lsp-catalog.md` and offer code intelligence for the languages detected in the repo (or planned in the stack). Note the per-tool asymmetry the catalog describes: opencode needs nothing; Claude Code needs binary + plugin.
3. **Agent-rules pointer** — whether to add the SDD block (below) to the project's rules files: `CLAUDE.md` (Claude Code) and/or `AGENTS.md` (opencode, Codex, and most other tools). Offer the ones matching the installed shims; both is fine.
4. **Model profile** — which model runs each phase group:

   | Group | Phases | Mixto (default) | Económico | Sesión |
   |---|---|---|---|---|
   | Reasoning-heavy | new, design | opus | sonnet | *(none)* |
   | Main work | init, tasks, run, review | sonnet | sonnet | *(none)* |
   | Mechanical | archive, status | haiku | haiku | *(none)* |

   Options: **Mixto** (as shipped, no edits needed), **Económico** (no opus), **Modelo de sesión** (remove every model override so all phases inherit the session model), or **Personalizado** (follow up asking one model per group).

### 7. Apply choices

- **MCPs**: write the chosen entries into the config of each installed adapter, per the "Per-tool wiring" section of the catalog (`.mcp.json` for Claude Code; the `mcp` block of `opencode.json` for opencode). Merge — preserve every existing server, only add new keys. Mention any auth step the catalog notes.
- **LSPs**: per the catalog — check each chosen language server binary (`which`), install missing ones with user approval, then print the exact `/plugin install <name>` command(s) for the user to run in Claude Code (the agent cannot run slash commands itself). For opencode, nothing to do unless the catalog says a custom `lsp` block is needed.
- **Agent-rules pointer**: append the block below to the chosen rules files (create if missing). Idempotent — if the markers already exist, replace the block content instead of duplicating:

```markdown
<!-- sdd:start -->
## Spec-Driven Development

This project uses the SDD workflow. Read `sdd/project.md` before significant work.
New features and non-trivial changes go through the phases in `sdd/workflow/` (shims: /sdd-new → /sdd-design → /sdd-tasks → /sdd-run → /sdd-archive; without shims, execute the phase files directly).
Current system behavior is documented in `sdd/specs/`; in-flight changes live in `sdd/changes/`; standing rules in `sdd/steering/`.
<!-- sdd:end -->
```

- **Model profile**: apply by editing the `model:` frontmatter line of every installed shim — `.claude/skills/sdd-*/SKILL.md` (values: `opus`, `sonnet`, `haiku`) and `.opencode/command/sdd-*.md` (values: `anthropic/<full-model-id>`; keep the model family the profile dictates and verify the exact ids the user's opencode install exposes). Add/replace the line for a model change; delete it for "Modelo de sesión". If the profile is Mixto and the files already match, touch nothing. Warn that re-running `install.sh` resets shims to the shipped defaults, so init's extras step should be re-run after updates if a non-default profile was chosen.
- Record enabled MCPs and the chosen model profile in the **Context** section of `sdd/project.md`.

### 8. Summarize

Report what was created/enabled. Suggest the first step: the `new` phase on the first roadmap entry if a roadmap exists, otherwise `new` with a feature the user has in mind.
