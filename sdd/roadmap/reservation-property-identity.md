# reservation-property-identity

[BE] **la lista de reservas identifica la vivienda con un UUID pelado**, y no por descuido
de la pantalla: no hay nada mejor que pintar.

> **Entregado.** PR #128, mergeado el 2026-08-25 y archivado el 2026-08-30. El
> comportamiento vivo está en `sdd/specs/reservations.md` §«Identidad legible de la vivienda
> y del huésped»; lo que sigue es la nota que justificó la entrada, no el estado actual.
>
> **Las tres preguntas abiertas de abajo quedaron contestadas así**: (1) **los dos campos**,
> `property_name` y `property_internal_code`, porque la columna debe poder enseñar cualquiera
> de los dos; (2) **el detalle recibe lo mismo que la lista**, ni más ni menos — ampliar el
> contexto del detalle habría sido unir permisos, que la decisión D10 de `dashboard-api.md`
> prohíbe; (3) **sí, `guest_id` sufría lo mismo**, y entró en el mismo alcance como
> `guest_full_name`.
>
> De §Fuera de alcance, `reservation-amount-empty-render` **ya se entregó** (archivado el
> 2026-08-25). Lo que sigue pendiente es **la UI**: medido el 2026-08-30,
> `frontend/features/reservations/components/list/reservations-view.tsx:159` todavía pinta
> `{row.propertyId}` y ni `propertyName` ni `guestFullName` aparecen en el frontend. El
> backend sirve los tres campos y nadie los consume, así que el defecto que abrió esta
> entrada —un UUID en la columna Property— **sigue en pantalla**. Entrada de roadmap:
> `reservations-identity-web`.

Descubierto analizando el export de Stitch del 2026-08-23. Su maqueta de reservas es la de
mayor fidelidad de las seis —hecha sobre la pantalla real— y pinta
`981b5c2e-11a4-401b-8459-a97d88b2c14e` en la columna **Property** porque lo copió de la
pantalla. Ver `docs/design/2026-08-23-stitch-export/README.md`.

## Medido, no supuesto

`reservations-view.tsx:159` pinta el campo que tiene:

```tsx
<td className="border-b px-2 py-1">{row.propertyId}</td>
```

Y no tiene otro, porque el contrato no lo da. `ReservationResponse` en
`backend/openapi.json` tiene **27 campos** y de la propiedad exactamente uno:

```
access_status, adults, channel, check_in_date, check_in_time, check_out_date,
check_out_time, children, cleaning_required, created_at, currency,
external_channel_id, external_pms_id, gross_amount, guest_id, id,
internal_notes, legal_registration_status, net_amount, nights, ota_commission,
payment_status, property_id, special_requests, status, total_guests, updated_at
```

Ni `property_name`, ni `property_internal_code`. `features/reservations/data/dto.ts:76` lo
refleja fielmente: `propertyId: string` y nada más. **El frontend no puede arreglar esto.**

## La forma de la solución ya existe dos veces en este roadmap

Este es el mismo problema, con el mismo enunciado, que ya se resolvió para otros dos roles:

- **`cleaner-task-context`** (entregado 2026-08-21) — *«el contexto que la limpiadora
  necesita para hacer la tarea, sin darle `READ_PROPERTIES` ni `READ_RESERVATIONS`»*:
  `CleaningTaskResponse` devolvía `property_id` y `reservation_id` como UUID pelados.
- **`tech-incident-context`** (entregado) — *«a qué piso va el técnico y cómo entra, sin
  darle `READ_PROPERTIES`»*: `IncidentResponse` devolvía `property_id` como UUID pelado.

Los dos resolvieron el contexto **en el servidor** en vez de hacer que el cliente pidiera
`/properties`. Esta entrada es el tercer caso y debe seguir su patrón, no inventar otro:
al abrir su `/sdd:new`, leer primero esos dos changes archivados y sus specs.

**Por qué el patrón importa y no es solo elegancia**: hacer que la pantalla de reservas
llame a `/api/v1/properties` para traducir UUID a nombre exigiría `READ_PROPERTIES` a quien
solo mira reservas — es decir, ampliar permisos para resolver una etiqueta. Eso es
exactamente lo que los dos precedentes rechazaron pagar, y `steering/security.md` regla 11
acota además qué campos pueden salir en una respuesta de lote. Es el argumento decisivo,
no el número de peticiones.

## Preguntas abiertas para su `/sdd:new`

1. **Qué campos exactamente.** La tabla necesita una etiqueta legible; `properties` tiene
   `name` **y** `internal_code`, y la maqueta del dashboard usa el código (`PAJARITOS8`,
   `REDES11`) mientras `properties-web` titula por `name`. Probablemente los dos, pero hay
   que decidirlo contra lo que la columna debe enseñar, no por simetría.
2. **Si el detalle recibe lo mismo o más.** `/reservations/[id]` tiene sitio para más
   contexto de vivienda que una celda de tabla; los dos precedentes ampliaron el contexto
   del *detalle*, no de la lista. Aquí la necesidad probada es la lista.
3. **Si `guest_id` sufre lo mismo.** `reservations-view.tsx:156` pinta
   `{row.guestId ?? "—"}` — un UUID de huésped, o una raya. La columna se llama **Guest** y
   nunca enseña un nombre, aunque `GuestSummary` tenga `fullName`. Es el mismo defecto en
   la fila de al lado y muy probablemente la misma solución; conviene medirlo al abrir la
   entrada y decidir si entra en el alcance o se separa.

## Fuera de alcance

El render del importe vacío (`?? ""` → `" EUR"`), que la misma maqueta destapó. Es
presentación pura y no toca el contrato: entrada `reservation-amount-empty-render`.
