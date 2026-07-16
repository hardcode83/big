# AutoHostAI

Capa operativa inteligente sobre un PMS/Channel Manager externo para viviendas turísticas. Ver `AutoHostAI_PRD_v5_Claude (1).md` para el PRD completo y `sdd/` para el flujo de desarrollo (Spec-Driven Development).

## Arrancar en local

Requisitos: Docker + Docker Compose v2, `make`.

```bash
cp .env.example .env   # rellena los valores (ver comentarios en el propio fichero)
make up                # levanta todo el stack: postgres, redis, backend, worker, frontend
```

Al cabo de unos segundos:

- Backend (FastAPI): http://localhost:8000/health
- Frontend (Next.js): http://localhost:3000 — muestra "backend: ok" cuando el backend responde
- Postgres: localhost:5432
- Redis: localhost:6379

```bash
make down              # para y elimina los contenedores del stack
make logs               # sigue los logs de todos los servicios
make ps                  # estado de los contenedores
```

### Levantar un solo componente

`SERVICE=` es opcional en `up`/`down`/`logs`/`sh`. Compose arranca automáticamente las dependencias declaradas de ese servicio:

```bash
make up SERVICE=backend    # backend + postgres + redis (sin frontend)
make up SERVICE=frontend   # frontend + backend + sus dependencias
make sh SERVICE=backend    # shell dentro del contenedor de backend
```

## Variables de entorno

Ver `.env.example` — nombres y formato esperado de cada variable, sin valores reales (nunca se commitea `.env`).

## Estructura

- `backend/` — FastAPI + Celery (Python, `uv`). Dockerfile en `backend/devops/Dockerfile`.
- `frontend/` — Next.js App Router (TypeScript, Tailwind). Dockerfile en `frontend/devops/Dockerfile`.
- `docker-compose.yml` / `Makefile` — orquestación del stack local, en la raíz.
- `sdd/` — flujo de Spec-Driven Development: specs, changes en curso, steering, roadmap.
- `docs/` — documentación extendida por capability y diagramas (`docs/diagrams/`: C4, hexagonal, ER, state machine, secuencias).

## Tests

```bash
cd backend && uv run pytest
cd frontend && npm test
```

## Desarrollo con SDD

Este proyecto se desarrolla con **Spec-Driven Development**: cada feature pasa por fases con aprobación humana entre ellas, y el estado completo vive versionado en [`sdd/`](sdd/README.md) — cualquier sesión de agente puede continuar donde lo dejó la anterior.

**Setup (una vez):** los comandos `/sdd:*` los da el plugin [sdd-toolkit](https://github.com/hardcode83/sdd-toolkit) de Claude Code:

```
/plugin marketplace add hardcode83/sdd-toolkit
/plugin install sdd@sdd-toolkit
```

**El ciclo de cada feature:**

| Paso | Comando | Resultado |
|---|---|---|
| 1 | `/sdd:status` | ¿Dónde estamos? Changes activos + roadmap como to-do list |
| 2 | `/sdd:new` | Proposal con requisitos EARS desde la siguiente entrada del roadmap (`sdd/roadmap.md`) — **apruebas tú** |
| 3 | `/sdd:design` | Decisiones técnicas (se salta si el cambio es trivial) — **apruebas tú** |
| 4 | `/sdd:tasks` | Checklist de tareas verificables — **apruebas tú** |
| 5 | `/sdd:run` | Implementa en orden; panel de revisores (architect/security/qa) por sección |
| 6 | `/sdd:archive` | Fusiona en `sdd/specs/`, actualiza README/`docs/`, archiva el change |

**Reglas del repo:**

- Los cambios no triviales entran por `/sdd:new`, nunca directo a código — así `sdd/specs/` sigue siendo la verdad de lo construido.
- Las reglas de arquitectura/seguridad/testing viven en `sdd/steering/` — son vinculantes para agentes (las carga cada fase y las verifica el panel) y para humanos.
- El PRD (`AutoHostAI_PRD_v5_Claude (1).md`) es la referencia funcional origen; el estado real del sistema son las specs.

Para aprender el flujo completo: [guía paso a paso](https://github.com/hardcode83/sdd-toolkit/blob/main/docs/guide.md) (10 min).
