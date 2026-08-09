# dashboard-api

[BE] **la API agregada que alimenta el dashboard del propietario**: los tres endpoints de lectura que `dashboard-web-frontend` dejó pendientes cuando adelantó la UI contra mocks (PRD §26.15-17, §9, §23, §24).

**Separada de `dashboard-web` el 2026-08-08**, por la misma costura que ya partió `guest-portal-api` / `guest-portal-web`, y por la misma razón que sacó `frontend-auth-session` de `dashboard-web` el 2026-08-07: la entrada original mezclaba la API agregada (backend) con el consumo (frontend) en un solo change, y un change SDD tiene una rama, un `tasks.md` y un `STATE.md` — la regla 10 de `rules.md` es «one feature, one branch, one working directory», así que no admite dos personas a la vez sin corromper la evidencia de `mark-ready`. Con el reparto de trabajo vigente (backend/infra y frontend en manos distintas) eso era un bloqueo estructural, no una preferencia de estilo. Partida, esta mitad **se puede empezar sin tocar un solo fichero de `frontend/`**.

## Lo que falta de verdad (verificado contra el código el 2026-08-08)

Sólo faltan **tres endpoints de lectura**, y uno de ellos necesita una capa `api/` que no existe:

- `GET /api/v1/properties/{id}/dashboard` — ausente.
- `GET /api/v1/properties/{id}/state` — ausente.
- `GET /api/v1/timeline/{property_id}` — ausente, y **`app/timeline/` no tiene carpeta `api/`**: hoy sólo hay `__init__.py`, `domain/` e `infrastructure/`. Hay que crear la capa entera, no añadir una ruta a un router existente.

El propio código lo declara y se lo asigna a este trabajo, en `app/properties/api/router.py:9-10`:

> *«Also absent: `GET /{id}/state` and `GET /{id}/dashboard` from §23:1942-1943. Those are the read surface of `dashboard-web`, and fixing their shape from here would pre-empt it.»*

## CORRECCIÓN de la entrada original (2026-08-08): el backend está mucho más avanzado

La redacción anterior de `sdd/roadmap/dashboard-web.md` afirmaba que «`backend/app/main.py:51-58` monta solo auth, users, reservations, integrations y tenants» y que **ninguno** de los tres endpoints que consulta `frontend/features/dashboard/data/dto.ts:11-12` existía. **Las dos afirmaciones se han quedado obsoletas** — se escribieron antes de archivar `properties-crud` (2026-08-08). Hoy:

- `main.py` monta **11 routers** (líneas 65-92): auth, users, reservations, integrations, tenants, properties, cleaning-checklist-templates, cleaning-tasks, notifications, access-records y guests. Más `GET /health`. Son **45 rutas** en `backend/openapi.json`.
- **`GET /api/v1/properties` y `GET /api/v1/properties/{id}` ya existen** (`app/properties/api/router.py:63` y `:148`), junto con `POST` y `PATCH`. O sea, **dos de los cuatro endpoints que el frontend necesita ya están servidos**; lo que falta es la parte agregada.

Corolario para el diseño: **el alcance es menor de lo que sugería la entrada original**, y por eso baja de `L` (cuando incluía el FE) a `M`.

Otra referencia que hay que dejar de arrastrar: la nota original decía que el swap del mock «es el instante en que se cumple la condición de disparo #1 de `api-ingress-routing`». **`api-ingress-routing` ya está archivada** (2026-08-08), así que esa condición está resuelta y no cuelga de aquí.

## Lo que NO incluye

- El consumo desde el frontend — es `dashboard-web`, que declara `needs: dashboard-api`.
- Cualquier vía de escritura. Los tres endpoints son de lectura pura; `properties-crud` ya entregó la escritura canónica y **no se toca**, que es lo que hace este change aditivo y sin riesgo de rotura.

## Renombrados pendientes por el split (grep hecho el 2026-08-08)

El split dejó **cinco referencias que atribuyen la mitad backend a `dashboard-web`** y ahora nombran el change equivocado. No se corrigieron al partir la entrada, a propósito: specs, código y docs pertenecen a un change, no a una edición de roadmap. **Se arreglan dentro de este change** — las cuatro primeras en su `run`, la de specs al archivar:

- `backend/app/properties/api/router.py:10` — *«Those are the read surface of `dashboard-web`»* → `dashboard-api`.
- `docs/properties.md:109` — *«(`/properties/{id}/state`, `/properties/{id}/dashboard`): están en PRD §23 y son de `dashboard-web`»* → `dashboard-api`.
- `docs/dashboard.md:9` — *«el backend agregado que lo alimentará … roadmap `dashboard-web`»* → `dashboard-api`. Este párrafo entero deja de ser cierto cuando este change entra: hay que actualizar el bloque «Estado: solo lectura sobre datos mock» (`docs/dashboard.md:5-10`), no sólo el nombre.
- `docs/properties.md:107` y las demás menciones del tipo «el frontend llega con `dashboard-web`» (`docs/reservations.md:145`, `sdd/specs/user-management.md:16,255`, `sdd/specs/reservations.md:16,286`) **son correctas y no se tocan**: se refieren al frontend, que sigue siendo `dashboard-web`.
- `sdd/specs/dashboard-web-frontend.md:116` — *«the app's own aggregate dashboard backend (roadmap `dashboard-web`)»* → `dashboard-api`. Es una spec viva, así que la escribe `/sdd:archive`, no el `run`.

Y una que **no** es de este change, porque vive en `frontend/` y es de la otra mitad: `frontend/features/dashboard/data/dashboard-source.ts:12` dice *«when dashboard-web (backend) ships»*, que tras el split es doblemente equívoco. Le corresponde a `dashboard-web`.

## Contrato

El contrato es la frontera real con el trabajo de frontend, y ya está escrito: la interfaz que `HttpDashboardSource` tendrá que satisfacer es `frontend/features/dashboard/data/dashboard-source.ts:23-41` (tres métodos: cards, detail, timeline), y las formas concretas están en `frontend/features/dashboard/data/dto.ts`, que declara en `:9-12` que son «the contract that `MockDashboardSource` satisfies today and `HttpDashboardSource` must satisfy tomorrow». **Diseñar los endpoints leyendo esos dos ficheros primero** evita que la mitad de frontend tenga que reescribir sus DTOs.

Al terminar hay que regenerar las dos mitades del contrato (`backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`): la CI lo verifica en `.github/workflows/frontend-api-contract.yml:41` (`npm run api:check`) y en `.github/workflows/api-contract.yml:85`, así que un diff sin regenerar sale en rojo.
