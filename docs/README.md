# Documentación — AutoHostAI

Documentación extendida de la aplicación, mantenida por el flujo SDD: al archivar cada change, la fase `archive` aplica el checklist de `sdd/steering/documentation.md` y actualiza lo que corresponda aquí.

- **Una página por capability operativa** (`<capability>.md`) — cómo se usa/opera cada módulo (limpiezas, incidencias, dashboard…). Se crean a medida que las capabilities se construyen; el *qué hace* el sistema está en `sdd/specs/`, aquí va el *cómo se trabaja con ello*.
- **`diagrams/`** — diagramas del sistema (C4, hexagonal, ER, state machine, secuencias), nombrados `{YYYY-MM-DD}_{slug}.png`. Se regeneran con `/sdd:diagram` cuando un change los deja obsoletos.
