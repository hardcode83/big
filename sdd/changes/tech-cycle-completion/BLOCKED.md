# Blocked / deferred — tech-cycle-completion

## 1. Los recuentos de `TimelineEventType` en dos specs vivas que el diseño no pudo prever

- **Phase**: archive
- **Type**: deferred (el flujo lo resuelve; no necesita decisión humana)
- **Resume**: `/sdd:archive tech-cycle-completion`

**Qué**: `TimelineEventType` pasa de 46 a 47 miembros con `TECHNICIAN_REJECTED`, y dos
specs vivas afirman el número viejo en cinco sitios:

- `sdd/specs/dashboard-web-frontend.md:110` — «the closed 46-value [vocabulary]»
- `sdd/specs/dashboard-web-frontend.md:122` — «19 of the 46 types have no production writer»
- `sdd/specs/dashboard-web-frontend.md:287` — «the closed 46-value vocabulary»
- `sdd/specs/dashboard-api.md:156` — «los 46 valores de `TimelineEventType` en ambos idiomas»
- `sdd/specs/dashboard-api.md:328` — «el catálogo de 46 tipos × 2 idiomas»

**Por qué no lo dice `design.md`**: cuando se escribió, esas dos specs no existían en esta
forma — las dejó `timeline-web`, que se archivó en `main` (`61beee4`) **mientras este change
estaba en revisión**. La lista de trabajo de archivado del diseño («Al archivar (no en
implementación)») nombra `maintenance.md`, `timeline-state-machine.md`, `api-contract.md`,
`docs/maintenance.md` y los dos diagramas; estas dos specs son adicionales y se descubrieron
al resolver el merge con `main`.

**Ojo con el 19**: no es un total, es un derivado, y se mueve por los **dos** lados. Este
change le da a `TECHNICIAN_EN_ROUTE` su primer escritor (R2.2) y añade `TECHNICIAN_REJECTED`
ya con escritor, así que la cifra de «sin escritor en producción» baja mientras el total sube.
**Recontar contra el código**, no decrementar de memoria — es la misma disciplina que D10 le
impone al censo de la regla 11, y por el mismo motivo.

## 2. La entrada de roadmap `assignment-note-storable-text`

- **Phase**: archive
- **Type**: deferred
- **Resume**: `/sdd:archive tech-cycle-completion`

`design.md` § Risks la levanta como observación fuera de alcance: `incidents.assignment_note`
es un sumidero vivo que **no** pasa por `storable_text`, así que un `U+0000` en esa nota sale
hoy como `500` sin declarar. `materials` sí lo lleva desde el primer día. Queda como candidato
de roadmap con nombre propio; el archivado decide si lo da de alta.
