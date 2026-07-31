# Reservas — cómo se operan

Qué hace el sistema con una reserva está en `sdd/specs/reservations.md` (criterios EARS).
Esta página es lo otro: **cómo se usa y se opera**.

La reserva es el dato del que cuelga la operación — la máquina de estados de la propiedad
resuelve su estado a partir de "reserva activa" y "próxima reserva", y limpieza, accesos y
mensajería se disparan desde su ciclo. Toda alta, edición, cancelación e importación deja un
evento en el timeline de la vivienda.

## Quién puede hacer qué

| Rol | Ver reservas | Crear / editar / cancelar | Importar CSV |
|---|---|---|---|
| `PROPERTY_MANAGER` | sí | sí | sí |
| `TENANT_OWNER` | sí | no (`403`) | no (`403`) |
| `CLEANER` | no | no | no |
| `TECHNICIAN` | no | no | no |
| `SUPER_ADMIN` | no | no | no |

Sale de PRD §6: el manager gestiona reservas, la propietaria las ve. `SUPER_ADMIN` tiene
poderes globales (tenants, configuración, integraciones), no operativos de un tenant — la
visibilidad cross-tenant es una decisión pendiente de la fase SaaS.

## Los endpoints

Todos bajo `/api/v1`, con `Authorization: Bearer <access_token>`. El contrato completo está en
el OpenAPI que sirve el propio backend (`/docs`).

```
GET    /reservations?page=1&per_page=20&property_id=&status=&date_from=&date_to=
POST   /reservations
GET    /reservations/{id}
PATCH  /reservations/{id}
DELETE /reservations/{id}
POST   /integrations/pms/import-csv        (multipart/form-data)
```

Detalles que importan al usarlos:

- **El rango de fechas filtra por solape de estancia**, no por fecha de entrada: un huésped que
  ya está en la vivienda cuando empieza el rango aparece en el resultado. Es lo que se pregunta
  de verdad ("qué reservas caen en estas fechas").
- **`DELETE` cancela, no borra.** La fila se conserva con `status: CANCELLED`, y repetir la
  llamada devuelve `204` sin duplicar el evento de cancelación. Un `PATCH` con
  `status: CANCELLED` hace lo mismo y deja el mismo evento.
- **`nights` y `total_guests` no se envían**: se derivan de las fechas y de la ocupación. Si los
  mandas, la petición se rechaza con `422`.
- **Crear a mano solo admite `MANUAL` o `DIRECT`.** Los canales de OTA llegan por el PMS o por
  el CSV, que traen `external_pms_id`; una reserva de Airbnb escrita a mano no lo tendría y la
  siguiente sincronización la importaría otra vez como fila nueva.
- **Una reserva de otro tenant responde `404`, nunca `403`** — la respuesta no revela que
  exista.

## Importar un CSV

`POST /api/v1/integrations/pms/import-csv` con el fichero en el campo `file`. UTF-8 (el BOM de
Excel se tolera), separador `,`.

Columnas requeridas: `property_internal_code`, `channel`, `check_in_date`, `check_out_date`,
`adults`.

Opcionales: `external_pms_id`, `external_channel_id`, `guest_name`, `guest_email`,
`guest_phone`, `children`, `check_in_time`, `check_out_time`, `gross_amount`,
`ota_commission`, `currency`, `status`, `special_requests`.

```csv
property_internal_code,channel,check_in_date,check_out_date,adults,guest_name,guest_email
REDES11,AIRBNB,2026-08-01,2026-08-04,2,John Smith,john.smith@example.com
```

La propiedad se nombra por su **código interno** (`REDES11`), no por UUID — lo rellena una
persona. Un código que no exista en tu tenant se reporta como error de esa fila.

La respuesta es un informe, no un simple OK:

```json
{"created": 12, "updated": 3, "skipped": 2,
 "errors": [{"line": 7, "reason": "check_in_date must be an ISO date (YYYY-MM-DD), got 'ayer'"}]}
```

- **Una fila mala no tira el fichero**: se omite, se informa con su número de línea (la cabecera
  es la línea 1) y las demás entran.
- **Reimportar el mismo fichero no duplica nada**: las filas con un `external_pms_id` ya
  conocido se actualizan. `created: 0` en la segunda pasada es la señal de que la idempotencia
  funciona.
- Un decimal con coma va **entrecomillado** (`"120,50"`), como lo escribe cualquier hoja de
  cálculo. Sin comillas, la fila tiene una columna de más y se reporta como error en lugar de
  importarse con los valores desplazados.
- Límites: `CSV_IMPORT_MAX_BYTES` (10 MB) y `CSV_IMPORT_MAX_ROWS` (1000). Pasarse de cualquiera
  de los dos da `413` y no importa ninguna fila.

## Sincronizar con el PMS

Hoy el adapter del PMS es **`MockPMSAdapter`** (`EXTERNAL_DEPENDENCY`): devuelve las reservas
del seed de PRD §27 y, a propósito, dos filas que fallan, para que el camino de error esté
ejercitado de verdad. Cuando haya credenciales de Octorate/Smoobu/Beds24 solo cambia la
implementación del puerto.

No hay endpoint de sincronización — el disparador natural es Celery beat, que llega con la
entrada `celery-jobs` del roadmap. Mientras tanto se ejecuta como comando:

```bash
docker compose exec backend uv run python -m app.integrations.cli.pms_sync <tenant-uuid> [días]
# pms-sync: created 2, updated 0, skipped 2
# pms-sync: skipped MOCK-PMS-9001 — Unknown property 'PMS-DOES-NOT-EXIST' for this tenant
```

Las filas omitidas van a `stderr` y **no** hacen fallar el comando: el run hizo lo que podía,
que es exactamente lo que se le pide. La propiedad se resuelve por `pms_external_id`, así que
cada vivienda debe llevar el suyo para que la sincronización la encuentre.

## Timeline: qué queda registrado

| Acción | Evento | Actor |
|---|---|---|
| Alta por API | `RESERVATION_CREATED_MANUAL` | `USER` (quien la creó) |
| Edición por API | `RESERVATION_UPDATED` | `USER` |
| Cancelación (`DELETE` o `PATCH` a `CANCELLED`) | `RESERVATION_CANCELLED` | `USER` |
| Alta por importación CSV | `RESERVATION_IMPORTED` | `USER` (quien subió el fichero) |
| Alta por sincronización PMS | `RESERVATION_IMPORTED` | `SYSTEM` |

El evento de edición registra **qué campos** cambiaron. En los campos de texto libre
(`internal_notes`, `special_requests`) registra que cambiaron pero **no su contenido**: el
timeline no se puede editar nunca, y un código de puerta pegado en una nota interna se quedaría
ahí en claro para siempre.

Una edición que no cambia nada (mismo valor, o cuerpo vacío) no escribe ni evento ni fila: el
timeline es evidencia de cambios, no de peticiones.

## Limitaciones conocidas

- **No hay recepción de webhooks** (`POST /api/v1/webhooks/{provider}` de PRD §16). Necesita la
  entidad `WebhookEvent` de `domain-foundation-financial` y el job `process_webhook_events` de
  `celery-jobs`, ninguna de las dos empezada.
- **No se escribe `AuditLog`** de las mutaciones: la entidad también pertenece a
  `domain-foundation-financial`. El rastro operativo mientras tanto es el `TimelineEvent`.
- **Una reserva no cambia el estado operacional de la vivienda**: esas transiciones dependen del
  reloj (`AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`, `CHECKOUT_WINDOW_REACHED`) y pertenecen a
  `celery-jobs`.
- **La API no sale a internet** todavía: el túnel enruta solo al frontend. Para probarla contra
  dev hace falta un túnel SSH (`infra/environments/dev/RUNBOOK.md` §7.4). Lo cambia la entrada
  `api-ingress-routing`.
- **No hay frontend de reservas**: llega con `dashboard-web`.
