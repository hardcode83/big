# BLOCKED: tech-app

## 1. El panel de review no puede dar PASS: los cuatro reviewers de proyecto son `unavailable`

- **phase**: run
- **type**: decision
- **what & why**: `sdd-toolkit` 0.40.0 estrena el gate ejecutable del panel
  (`skills/reviewer-panel/reviewer_plan.py`, que no existe en 0.38.0 ni en 0.39.0). Su parser de
  reviewers de proyecto (`_parse_project`) admite **exactamente tres** claves de frontmatter —
  `name`, `phases`, `applies_to` — y lanza `unsupported or duplicate frontmatter field` ante
  cualquier otra. Los cuatro ficheros de `.claude/agents/sdd-review-*.md` de este repo llevan
  `description`, `model` y `tools`, que es lo que Claude Code necesita para poder lanzarlos como
  agentes. Verificado uno a uno: los cuatro fallan el parseo.

  Consecuencia: `build_reviewer_plan` los marca `lens: unavailable` y `dispatch_status:
  unavailable`; `evaluate_panel_gate` añade incondicionalmente el error `"unavailable reviewer in
  plan"`. **Ninguna sección de este repo puede recibir `panel: PASS` bajo 0.40.0**, con
  independencia de lo que digan los reviewers.

  No hay frontmatter que satisfaga a los dos lados: Claude Code exige `description` y el parser del
  toolkit lo prohíbe. Es un fallo del toolkit (debería tolerar claves de más), no una
  desconfiguración del repo, así que **no se toca `.claude/agents/`**: son ficheros compartidos y
  hay tres sesiones vivas en paralelo.

  Lo que se hizo en su lugar: implementar las secciones verificando cada una con la suite, el
  typecheck y el lint, y **no anotar `panel: PASS` en ninguna** — el gate es fail-closed y una
  anotación sin gate sería exactamente la evidencia falsa que la regla 8 prohíbe.

- **exact resume command**: `/sdd:review tech-app`
  (cubre el panel a escala de feature; requiere antes que el gate del panel sea capaz de pasar —
  esto es, un toolkit que tolere el frontmatter de Claude Code, o una decisión explícita sobre qué
  hacer con `.claude/agents/sdd-review-*.md`).

## 2. La comprobación visual del flujo (9.5) y la de 360 px (9.6) siguen pendientes

- **phase**: run
- **type**: deferred
- **what & why**: las dos tareas piden mirar la aplicación de verdad: recorrer
  `ASSIGNED → ACCEPTED → IN_PROGRESS → RESOLVED` con un usuario `TECHNICIAN`, subir una foto
  `BEFORE` y otra `AFTER`, cerrar con coste y materiales, comprobar en la pestaña de red que abrir
  una fila no vuelve a pedir su contexto, y revisar a 360 px que no hay desplazamiento horizontal.

  No se han hecho. Este worktree está enlazado y **no publica puertos**, así que no hay UI
  alcanzable desde el host; y con `make up PORT_OFFSET=<n>` la página se sirve pero **no hidrata**
  (`sdd/project.md`, medido en `cleaning-assign-preconditions` el 2026-08-23: submit nativo del
  formulario, el conmutador de idioma muerto y ninguna prop de React en el `<form>`), de modo que
  ni los botones del ciclo ni el formulario de cierre responderían — que es exactamente lo que hay
  que probar. La salida documentada es el **worktree principal** o `dev`, y el principal lo están
  usando otras sesiones vivas, así que no se le toca el stack.

  Lo que sí está verificado y no sustituye a lo anterior: la suite completa del frontend en verde
  (163 ficheros / 1653 tests), typecheck y lint limpios, y 75 tests propios de `features/tech` que
  cubren por composición cada criterio de R1–R6. **Un test de componente no es una pasada visual**:
  no dice nada del desplazamiento horizontal real ni de si los objetivos táctiles son cómodos con
  el pulgar.

- **exact resume command**: `/sdd:review tech-app` (desde el worktree principal, o contra `dev`)
