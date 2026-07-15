# SDD — Spec-Driven Development

Este directorio contiene las specs del proyecto **y** la definición del flujo — es la capa de persistencia completa: cualquier agente de código (Claude Code, opencode, Codex…) puede abrir el repo y continuar el trabajo desde aquí. Convenciones para humanos y agentes:

- `workflow/` — definición agnóstica de las fases SDD (init/new/design/tasks/run/archive/status/review), sus templates y referencias. Propiedad del toolkit: se refresca al actualizar, no se edita a mano. Los comandos por herramienta (`/sdd-*`) son shims que apuntan aquí; sin shims, pide a tu agente: *"lee sdd/workflow/README.md y ejecuta sdd/workflow/<fase>.md"*.
- `project.md` — steering core: stack, comandos de build/test/lint, convenciones. Generado por `/sdd-init`, editable a mano. Se lee al inicio de toda fase SDD.
- `steering/` — reglas permanentes ricas: `product.md` (visión), `architecture.md`, `security.md`, docs por componente/lenguaje. Cada doc declara en su frontmatter (`applies_to`, `phases`) cuándo se carga — las fases SDD solo leen los que aplican al cambio en curso.
- `specs/` — **verdad viva**: qué hace el sistema hoy. Una capability por archivo, en presente, con requisitos EARS. Solo se actualiza al archivar un cambio completado (`/sdd-archive`). En proyectos que adoptaron SDD con código existente, la cobertura crece por "spec on first touch".
- `changes/` — cambios en curso. Cada carpeta es un cambio con `proposal.md` (por qué + requisitos), `design.md` (opcional, decisiones técnicas) y `tasks.md` (checklist).
- `changes/archive/` — cambios completados, con prefijo de fecha.
- `roadmap.md` — (opcional) backlog ordenado de futuros changes, una línea por feature. `/sdd-new` coge la siguiente entrada y la convierte en proposal just-in-time.

Flujo: `/sdd-new` → `/sdd-design` → `/sdd-tasks` → `/sdd-run` → `/sdd-archive`. Cada fase requiere aprobación humana antes de la siguiente.
