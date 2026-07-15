# Steering docs — format and loading rules

Steering docs live in `sdd/steering/` and hold the standing rules of the
project: product vision, architecture, security, per-component and
per-language conventions. They are richer than `project.md` (which stays a
short always-read summary) and are loaded **selectively** by the SDD phase
skills, so a frontend change never pays the context cost of the terraform
guide.

## Frontmatter

Each doc declares when it applies. Both fields are optional — omitting one
means "always".

```yaml
---
applies_to: ["frontend/**", "*.tsx"]   # glob paths; omit = every change
phases: [new, design, tasks, run]      # SDD phases; omit = all phases
---
```

Valid phase values: `new`, `design`, `tasks`, `run`, `archive`.

## Loading rule (implemented by each phase skill)

At the start of a phase, after reading `sdd/project.md`: if `sdd/steering/`
exists, read each doc's frontmatter and load the full doc when **both**:

1. `phases` is absent or includes the current phase, and
2. `applies_to` is absent or matches the files/areas the change touches
   (for `/sdd-new`, judge by the areas the request describes; for later
   phases, use the proposal's scope and the actual files being modified).

## Recommended frontmatter per doc type

| Doc | applies_to | phases |
|---|---|---|
| `product.md` | *(omit)* | `[new, design]` |
| `architecture.md` | *(omit)* | `[design, tasks]` |
| `security.md` | *(omit)* | `[design, run]` |
| `testing.md` | *(omit)* | `[tasks, run]` |
| `documentation.md` | *(omit)* | `[tasks, archive]` |
| `frontend.md` / `backend.md` / `infra.md` | component paths | *(omit)* |
| `python.md` / `typescript.md` … | `["**/*.py"]` etc. | `[tasks, run]` |

Adjust per project — these are defaults, not law. Keep each doc focused and
under ~100 lines; if a doc grows past that, split it by scope so the loading
rule can do its job.
