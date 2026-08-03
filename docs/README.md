# Documentación — AutoHostAI

Documentación extendida de la aplicación, mantenida por el flujo SDD: al archivar cada change, la fase `archive` aplica el checklist de `sdd/steering/documentation.md` y actualiza lo que corresponda aquí.

- **Una página por capability operativa** (`<capability>.md`) — cómo se usa/opera cada módulo (limpiezas, incidencias, dashboard…). Se crean a medida que las capabilities se construyen; el *qué hace* el sistema está en `sdd/specs/`, aquí va el *cómo se trabaja con ello*.
- **[`channex-staging.md`](channex-staging.md)** — runbook del sandbox de Channex que valida el backend contra un PMS real, y los hallazgos medidos contra su API (filtro temporal que ignora la zona horaria, comisión que no distingue cero de ausencia, vocabulario de estado propio, paginación). Incluye la **regla dura** de no conectar nunca las cuentas reales de OTA.
- **`adr/`** — Architecture Decision Records, numerados `NNNN-slug.md`. Registran decisiones estructurales con su contexto, sus consecuencias y las alternativas rechazadas. Cuando una decisión se aparta del PRD, **el PRD no se edita**: la desviación vive en el ADR y llega a las specs al archivar el change que la implemente.
- **`diagrams/`** — diagramas del sistema (C4, hexagonal, ER, state machine, secuencias), nombrados `{YYYY-MM-DD}_{slug}.png`. Se regeneran con `/sdd:diagram` cuando un change los deja obsoletos.
