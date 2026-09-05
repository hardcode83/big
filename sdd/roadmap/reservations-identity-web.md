# reservations-identity-web

[FE] **el backend ya sirve el nombre de la vivienda y del huésped, y la pantalla sigue pintando el
UUID**.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04): es la predecesora de `reservation-create-web`, y la única dependencia interna del
> hito. Elegida el 2026-09-05 como **primera entrada en modo auto** porque no tiene ninguna
> decisión abierta: el contrato está publicado, los campos existen, y la regla de render de los
> nulos ya está escrita en `specs/frontend-foundation.md`.

**El hecho medido (2026-08-30, revalidado 2026-09-05)**: `reservation-property-identity`
(mergeado el 2026-08-25, archivado en `sdd/changes/archive/2026-08-30-reservation-property-identity/`)
añadió `property_name`, `property_internal_code` y `guest_full_name` a `GET /api/v1/reservations`
y a `GET /api/v1/reservations/{id}`, como campos **derivados de lectura, nunca persistidos**
(`backend/app/reservations/domain/entities.py:114-118`). En el frontend **nadie los consume**:
`frontend/features/reservations/components/list/reservations-view.tsx:172` sigue con
`{row.propertyId}`, y `frontend/features/reservations/data/dto.ts:76` sólo declara `propertyId`
—su comentario de :133 explica que un *picker* de propiedad quedaba fuera de v1, que es otra cosa—.
Ninguno de los tres campos aparece en `frontend/features/reservations/**`.

**Por qué no es cosmético**: es la mitad que cierra el defecto que abrió aquella entrada — la
columna *Property* de la maqueta de Stitch enseñando `981b5c2e-…` en vez de `REDES11`. Y con
`reservation-create-web` detrás, construir un formulario de alta sobre una lista que identifica la
vivienda por UUID es construir sobre algo que hay que rehacer.

**Alcance, sin backend**:

1. Regenerar el DTO desde el contrato (`frontend/lib/api/generated/openapi.d.ts` ya lleva los
   campos si `backend/openapi.json` está al día; `cd frontend && npm run api:check` lo confirma —
   **en un worktree ese comando literal no funciona**, ver `sdd/project.md` §Worktree bootstrap
   para la salida con `docker compose cp`).
2. Mapear `property_name`, `property_internal_code`, `guest_full_name` en `dto.ts` y su mapper.
3. Pintar en la **lista**: columna *Property* con `property_internal_code` (y `property_name` como
   título/secundario, decisión de maqueta) y columna *Guest* con `guest_full_name`.
4. Pintar en el **detalle** (`components/detail/`) los mismos dos.
5. Los tres campos son `nullable` en el contrato: `—` (em-dash) cuando falten, la regla de
   `specs/frontend-foundation.md` que `reservation-amount-empty-render` ya reforzó en esta misma
   feature — nunca un `undefined` ni un string vacío.
6. i18n: las dos cabeceras nuevas en `locales/es` **y** `locales/en` (`steering/frontend.md`); el
   revisor `sdd-review-i18n` lo comprueba.
7. Tests: los del listado y del detalle renderizan el caso con valor y el caso `null`; y el test de
   contrato del DTO, si existe, se amplía.

**Lo que NO decide**: nada de forma nueva. Si al implementar aparece una decisión —por ejemplo,
que la maqueta de Stitch (`docs/design/2026-08-23-stitch-export/`) pida el nombre y no el código—,
se toma la más simple (código en la celda, nombre en `title`) y se anota; no es motivo de `BLOCKED`.

**Fuera de alcance**: crear/editar/cancelar (`reservation-create-web`); filtrar por propiedad o
enlazar a `/properties/[id]` desde la fila (candidato menor si sale gratis); tocar el backend o
`openapi.json`.

**Verificación**: `/reservations` en dev muestra `REDES11` y `John Smith` en las filas del seed, el
detalle también, y una reserva sin huésped enlazado muestra `—`. `npm test` sin ficheros nuevos
en rojo respecto a la cifra de partida (`sdd/project.md` explica los dos `ENOENT` del worktree).
