---
phases: [tasks, archive]
---

# Documentation — AutoHostAI

<!-- sdd/specs/ documenta el comportamiento y se mantiene solo al archivar;
     estas reglas cubren lo demás. -->

## Qué debe mantenerse al día (genera tareas)

- Endpoint nuevo/cambiado → visible en OpenAPI auto-generado (FastAPI); anotar summary/description y modelos de respuesta. **Regenerar `backend/openapi.json` con `make openapi` y commitearlo en el mismo PR** — el workflow `api-contract` lo exige. **Y regenerar también el artefacto derivado del frontend** (`cd frontend && npm run api:generate`, que reescribe `frontend/lib/api/generated/openapi.d.ts`) y commitearlo con él: el workflow `frontend-api-contract` comprueba que no haya deriva, y ese fichero está versionado igual que el contrato. Son **las dos mitades del mismo puente** — el contrato es la frontera entre los dos CI y cada lado tiene su artefacto. Añadido el 2026-08-08 tras romper `main` con el change `cleaning`: se regeneró el lado del backend, la regla se cumplió al pie de la letra, y el panel de documentación lo dio por conforme porque esta segunda mitad no estaba escrita en ninguna parte contra la que fallar.
- Variable de entorno nueva → `.env.example` actualizado con nombre y comentario, sin valores (PRD §25).
- String de UI nueva → claves en `locales/es/` **y** `locales/en/`.
- Supuesto o proveedor sin credenciales → marcar `ASSUMPTION` / `EXTERNAL_DEPENDENCY` donde corresponda.
- Cambio en arranque local → `README.md` de raíz (objetivo: `docker compose up` y listo, DoD §28.20).
- **README raíz al día por change**: si el change añade un módulo/servicio, comando de Makefile, o cambia la estructura de carpetas → actualizar las secciones Estructura/Arrancar/Tests del README. El README describe el sistema *actual*, nunca el planeado.
- **`docs/` — documentación extendida por capability**: al archivar un change que introduce o cambia una capability de cara a usuarios/operación (flujos de limpieza, incidencias, dashboard…), crear o actualizar su página `docs/<capability>.md` — orientada a *cómo se usa/opera* (las specs EARS de `sdd/specs/` ya cubren el *qué hace*; no duplicar, enlazar).
- **Diagramas en `docs/diagrams/`**: los diagramas viven ahí (nombrado `{YYYY-MM-DD}_{slug}.png`), nunca en la raíz. Si el change altera arquitectura, flujos o modelo de datos de forma que un diagrama existente queda obsoleto → regenerarlo con `/sdd:diagram` y reemplazar la referencia; los obsoletos se borran, no se acumulan.

## Audiencias

- README raíz: cómo arrancar, estructura, seed users (PRD §27), URLs locales, cómo se desarrolla (SDD).
- `docs/`: documentación extendida — una página por capability operativa + `docs/diagrams/`.
- OpenAPI/Swagger: contrato para el frontend. Vive **versionado** en `backend/openapi.json`, regenerado con `make openapi`; el `/docs` servido es la misma información, pero solo con el stack levantado. El workflow `api-contract` falla si el fichero commiteado no corresponde al código, así que un cambio de forma de una respuesta se ve en el diff de su Pull Request. **No es una red de seguridad contra cambios incompatibles**: eso lo atrapa el typecheck del frontend contra los tipos derivados (entrada `frontend-ci` del roadmap).
- `sdd/specs/`: comportamiento del sistema (lo mantiene el flujo SDD).

## Checklist de archivado

- [ ] Reglas de arriba aplicadas a todo lo tocado por el change.
- [ ] README raíz refleja el sistema tras el change (estructura, comandos, módulos).
- [ ] `docs/<capability>.md` creada/actualizada si el change tocó una capability operativa.
- [ ] Diagramas afectados regenerados en `docs/diagrams/`; ninguno obsoleto ni fuera de ese directorio.
- [ ] Ninguna doc referencia comportamiento eliminado por el change.
