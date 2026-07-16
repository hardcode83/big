# SDD — Spec-Driven Development

Este directorio es la **capa de persistencia** del proyecto para el flujo SDD (plugin `sdd` de Claude Code): specs, cambios en curso, reglas y roadmap viven en archivos, no en la sesión. Convenciones para humanos y agentes:

- `project.md` — steering core: stack, comandos de build/test/lint, convenciones. Generado por `/sdd-toolkit:init`, editable a mano. Se lee al inicio de toda fase SDD.
- `steering/` — reglas permanentes ricas: `product.md` (visión), `architecture.md`, `security.md`, `testing.md`, `documentation.md`, docs por componente/lenguaje. Cada doc declara en su frontmatter (`applies_to`, `phases`) cuándo se carga — las fases SDD solo leen los que aplican al cambio en curso.
- `specs/` — **verdad viva**: qué hace el sistema hoy. Una capability por archivo, en presente, con requisitos EARS. Solo se actualiza al archivar un cambio completado (`/sdd-toolkit:archive`). En proyectos que adoptaron SDD con código existente, la cobertura crece por "spec on first touch".
- `changes/` — cambios en curso. Cada carpeta es un cambio con `proposal.md` (por qué + requisitos), `design.md` (opcional, decisiones técnicas), `tasks.md` (checklist) y `metrics.md` (uso, si está activado).
- `changes/archive/` — cambios completados, con prefijo de fecha.
- `roadmap.md` — (opcional) backlog ordenado de futuros changes, una línea por feature. `/sdd-toolkit:new` coge la siguiente entrada y la convierte en proposal just-in-time. Editable a mano.
- `metrics.md` — (opcional) resumen de tokens/coste por feature archivada.

Flujo: `/sdd-toolkit:new` → `/sdd-toolkit:design` (opcional si trivial) → `/sdd-toolkit:tasks` → `/sdd-toolkit:run` → `/sdd-toolkit:archive`, con `/sdd-toolkit:status` y `/sdd-toolkit:review` como apoyo. Cada fase requiere aprobación humana antes de la siguiente.
