---
phases: [tasks, archive]
---

# Documentation — AutoHostAI

<!-- sdd/specs/ documenta el comportamiento y se mantiene solo al archivar;
     estas reglas cubren lo demás. -->

## Qué debe mantenerse al día (genera tareas)

- Endpoint nuevo/cambiado → visible en OpenAPI auto-generado (FastAPI); anotar summary/description y modelos de respuesta.
- Variable de entorno nueva → `.env.example` actualizado con nombre y comentario, sin valores (PRD §25).
- String de UI nueva → claves en `locales/es/` **y** `locales/en/`.
- Supuesto o proveedor sin credenciales → marcar `ASSUMPTION` / `EXTERNAL_DEPENDENCY` donde corresponda.
- Cambio en arranque local → `README.md` de raíz (objetivo: `docker compose up` y listo, DoD §28.20).

## Audiencias

- README raíz: cómo arrancar, seed users (PRD §27), URLs locales.
- OpenAPI/Swagger: contrato para el frontend.
- `sdd/specs/`: comportamiento del sistema (lo mantiene el flujo SDD).

## Checklist de archivado

- [ ] Reglas de arriba aplicadas a todo lo tocado por el change.
- [ ] Ninguna doc referencia comportamiento eliminado por el change.
