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

## Reviewer QA no disponible por créditos

- **phase**: review
- **type**: deferred
- **what & why**: El reviewer obligatorio sdd-qa no pudo completar el review porque el workspace se quedó sin créditos. El gate fail-closed no puede certificarse con una colección incompleta; no se sustituyó el reviewer.
- **exact resume command**: /sdd:review statements-web

## Reconciliación de certificaciones de secciones 1 y 2

- **phase**: run
- **type**: deferred
- **what & why**: Las tareas 1.1-1.4 y 2.1-2.3 están marcadas [x] y tienen verificaciones de implementación documentadas, pero sus secciones no llevan marcador panel: PASS persistido. Debe ejecutarse la revisión de reconciliación correspondiente sin declarar esas secciones certificadas ni repetir su implementación.
- **exact resume command**: /sdd:review statements-web

## Reset de filtros/page tras cambio de tenant

- **phase**: review
- **type**: deferred
- **what & why**: Finding sdd-architect, frontend/features/statements/components/statements-view.tsx:40, referent R1.3/D5: el reset en useEffect ocurre después del render que ya pasa estado del tenant anterior a la query; la primera petición del nuevo tenant puede usar propertyId/page obsoletos.
- **exact resume command**: /sdd:review statements-web

## Descarga pendiente ante cambio de tenant

- **phase**: review
- **type**: deferred
- **what & why**: Finding sdd-security, frontend/features/statements/hooks/use-statement-download.ts:25, referent R1.3/D5 y security rule 1: una exportación iniciada con tenant A puede completarse y entregarse tras logout o cambio a tenant B sin revalidar la identidad.
- **exact resume command**: /sdd:review statements-web

## Marcador de importe ausente sin i18n

- **phase**: review
- **type**: deferred
- **what & why**: Finding sdd-review-i18n, frontend/features/statements/components/reservations-breakdown.tsx:58, referent R5.4 y steering/frontend.md: el valor visible "—" está hardcodeado y no pasa por los catálogos ES/EN.
- **exact resume command**: /sdd:review statements-web

## Estado de refetch del listado

- **phase**: review
- **type**: deferred
- **what & why**: Finding sdd-review-ui-ux, frontend/features/statements/components/statements-list.tsx:61, referent R5.1: al refetchear por filtros/página solo se considera isPending, por lo que la lista puede quedar interactiva mostrando datos stale sin estado explícito de carga.
- **exact resume command**: /sdd:review statements-web

## Target táctil del retry del listado

- **phase**: review
- **type**: deferred
- **what & why**: Finding sdd-review-ui-ux, frontend/features/statements/components/statements-list.tsx:66, referent steering/frontend.md interaction targets: el retry de ErrorState usa el Button de 40px sin tap-target y queda por debajo del mínimo de 44px.
- **exact resume command**: /sdd:review statements-web

## Verificación 7.3 layout responsive y accesibilidad

- **phase**: run
- **type**: deferred
- **tasks**: 7.3
- **what & why**: Playwright no está instalado en el contenedor de este worktree (mismo problema documentado en sdd/project.md § 'Y npm test tiene el mismo problema'). La auditoría mobile-first de los componentes está cubierta por el panel PASS de la sección 6 (sdd-review-ui-ux) y por getA11yViolations en los tests de componente que sí corren; este test sólo reproduce la verificación contra un viewport real.
- **exact resume command**: /sdd:run statements-web 7.3
