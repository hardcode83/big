# SDD Workflow — agent-agnostic execution rules

This directory defines the SDD workflow. It is **tool-neutral**: any coding
agent (Claude Code, opencode, Codex, Cursor, …) can run a phase by reading its
file and following it. Tool-specific commands (`/sdd-new`, etc.) are thin shims
that point here — if your tool has no shims installed, just tell the agent:
*"Read sdd/workflow/README.md and execute sdd/workflow/<phase>.md with argument X"*.

This directory is owned by the SDD toolkit and refreshed on update — don't
edit in place; project-specific rules belong in `sdd/project.md` and
`sdd/steering/`.

## Shared rules (apply to every phase)

1. **State lives in `sdd/`, not in the tool.** Specs, changes, steering,
   roadmap — everything an agent needs to continue this project is in these
   markdown files. Keep them truthful: specs match code, checkboxes match
   verified reality. Never rely on conversation memory for state.
2. **Language**: write generated documents in the language the user
   communicates in.
3. **Phase gates**: end each phase by presenting a summary and waiting for
   explicit user approval. Never chain into the next phase automatically.
4. **Asking the user**: when a phase says "ask the user", present concrete
   options (numbered, or via the tool's native question UI if it has one).
5. **Context loading**: read `sdd/project.md` at the start of every phase.
   Steering docs in `sdd/steering/` load selectively per
   `references/steering.md`.

## Phases

| Phase | File | Purpose |
|---|---|---|
| init | `init.md` | Bootstrap SDD in the project (steering, baseline, extras) |
| new | `new.md` | Create a change proposal (EARS requirements) |
| design | `design.md` | Technical design (optional for trivial changes) |
| tasks | `tasks.md` | Implementation checklist |
| run | `run.md` | Execute tasks, verified, in order |
| archive | `archive.md` | Merge into living specs, archive the change |
| status | `status.md` | Report state of changes and roadmap |
| review | `review.md` | Spec-vs-code drift check / pre-archive review |
