# BLOCKED — statements-web

One entry per pending item (shared rule 5): `decision` needs a human before the change can move; `deferred` and `assumed` travel with the PR and are acknowledged by deleting them; `/sdd:archive` refuses to close while any entry remains.

## Revisión arquitectónica automática no disponible

- **phase**: design
- **type**: deferred
- **what & why**: El reviewer sdd-architect no pudo iniciar: claude está instalado, pero la sesión headless responde «Not logged in · Please run /login». El gate obligatorio no puede cerrarse de forma segura sin ese reviewer.
- **exact resume command**: /sdd:auto statements-web

## Delegación auto no autenticada tras reintento

- **phase**: auto
- **type**: deferred
- **what & why**: La receta headless se reintentó una vez y ambas sesiones terminaron con API error: Not logged in · Please run /login. No se puede ejecutar el reviewer arquitectónico ni continuar el pipeline unattended hasta que claude tenga autenticación válida.
- **exact resume command**: /sdd:auto statements-web

## Panel SDD de la sección 1 no disponible

- **phase**: run
- **type**: deferred
- **what & why**: Los cinco reviewers read-only fallaron dentro del sandbox con Operation not permitted; el reintento escalado fue rechazado porque podría transmitir código privado a un servicio Codex externo sin autorización específica. Las tareas 1.1-1.4, sus 38 tests acotados, typecheck y ESLint sí están verificados, pero el gate no puede escribir panel: PASS.
- **exact resume command**: /sdd:review statements-web

## Panel de la sección 1 no puede persistir el recibo

- **phase**: run
- **type**: deferred
- **what & why**: Los cinco reviewers devolvieron PASS, pero reviewer_panel.py no puede escribir el recibo requerido en el git common dir: Operation not permitted en .git/sdd/receipts/statements-web-run-1.json.
- **exact resume command**: /sdd:review statements-web

## Finding arquitectónico en la costura de propiedades

- **phase**: review
- **type**: deferred
- **what & why**: sdd-architect encontró que frontend/features/statements/data/index.ts reexporta useActiveProperties desde el barrel de properties, que también expone UI; esto acopla la capa data a exports de presentación y contradice D1/D2. El gate review persistió FAIL en el receipt canónico.
- **exact resume command**: /sdd:review statements-web

## Implementation Note contradice la corrección arquitectónica

- **phase**: review
- **type**: decision
- **what & why**: El re-review de sdd-architect encontró en sdd/changes/statements-web/tasks.md:135 una nota que todavía dice que features/statements/data reexporta useActiveProperties. El código ya no lo hace; la nota contradice D1/D2 y puede guiar incorrectamente la implementación de la sección 2. Se requiere decidir/corregir esa documentación antes de continuar.
- **exact resume command**: /sdd:review statements-web

## Reviewer QA no disponible por créditos

- **phase**: review
- **type**: deferred
- **what & why**: El reviewer obligatorio sdd-qa no pudo completar el review porque el workspace se quedó sin créditos. El gate fail-closed no puede certificarse con una colección incompleta; no se sustituyó el reviewer.
- **exact resume command**: /sdd:review statements-web
