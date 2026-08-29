# Accesos, notificaciones y registro legal

Cómo se opera lo que trajo el change `access-notifications`: la entrega de notificaciones
(PRD §14), el registro de accesos del huésped (§15) y la capa operativa de SES.Hospedajes
(§17). El *qué hace* está en [`sdd/specs/access-notifications.md`](../sdd/specs/access-notifications.md);
esta página es el *cómo se usa y se diagnostica*.

## Lo que cambió de golpe: el SLA dejó de estar inerte

Antes de este change, `check_sla_breaches` corría cada minuto y **nunca encontraba nada**. La
consulta de candidatos exige `status = SENT` y ningún código escribía ese valor, porque el
emisor no existía. Los plazos se escribían y vencían sin que nadie escalase.

Ahora `dispatch_notifications` entrega y marca `SENT`, así que la cadena funciona entera. Dos
consecuencias que conviene tener presentes al desplegar:

1. **El primer tick escala de golpe todo lo vencido.** Las filas `CLEANING_TASK_ASSIGNED` con
   plazo ya pasado pasan a ser candidatas en cuanto se entregan. Son incumplimientos reales
   —nadie respondió—, así que el aviso es correcto; el volumen puede sorprender.
2. **Responder cierra el plazo.** Aceptar o rechazar una limpieza anula su `sla_deadline_at`,
   de modo que una limpiadora que acepta en diez segundos no genera un escalado cuatro horas
   más tarde.

## Notificaciones

### Canales

| Canal | Adapter | Qué hace hoy |
|---|---|---|
| `EMAIL` / `CONSOLE` | `ConsoleEmailAdapter` | Registra la entrega en el log. SMTP real llega con `hardening-release` |
| `WHATSAPP` | `MockWhatsAppAdapter` | Mock (PRD §14) |
| `IN_APP` | `InAppNotificationAdapter` | No envía nada: **la fila es la entrega**, y la bandeja web es lo que la hace legible — y desde `notifications-inbox-web`, acusable |
| `PUSH` | — | Sin adapter a propósito: una fila `PUSH` pasa a `SKIPPED` |

### Leer la bandeja, y acusarla

El ciclo in-app se cierra con cuatro rutas. **Todas derivan el destinatario del JWT** y ninguna
acepta un parámetro que ensanche ese alcance.

```
GET  /api/v1/notifications?page=1&per_page=20[&unread=true]
GET  /api/v1/notifications/unread-count          -> {"unread": 3}
POST /api/v1/notifications/{id}/read             -> 204
POST /api/v1/notifications/read-all              -> {"updated": 7}
```

Ordenadas de más nueva a más vieja. `?unread=true` acota a las no leídas sin tocar el envelope
de PRD §23; ausente y `false` significan lo mismo.

**El acuse es idempotente y guarda la PRIMERA lectura**, no la última visita: la escritura es
`SET read_at = COALESCE(read_at, now)`, así que acusar dos veces responde `204` las dos y no
mueve el valor. Una notificación que no existe, que es de otro usuario o que es de otro tenant
responde el **mismo `404` con el mismo cuerpo** — un `403` confirmaría que existe una fila
ajena, y el mensaje del error es constante para que dos ids distintos no den dos cuerpos
distintos.

`read-all` nunca da `404`: cero filas es el caso normal de una bandeja al día.

El contador es ruta propia y no un campo del envelope, para que la campana pueda refrescarse
cada 60 s sin arrastrar una página de filas. Lo sostiene un índice **parcial**
(`ix_notification_logs_unread`, `WHERE read_at IS NULL`), que es la única forma de que su coste
no crezca con las ya leídas.

**Acusar no toca el SLA.** `read_at` queda fuera de `check_sla_breaches`, de
`list_sla_breach_candidates` y de `escalation_for`: leer un aviso no es responder a él, y el
plazo lo cierra la acción de dominio.

La respuesta lleva `subject`, `body`, `status`, `read_at` y los identificadores. **No** lleva
`recipient_contact` ni `last_error`: el primero convertiría la bandeja en un directorio, el
segundo es diagnóstico de operación.

`notification_type` viaja como `NotificationType | str` — unión, no enum a secas: la columna es
`String(100)` libre y admite valores anteriores al enum, y estrecharla convertiría ese caso en
un `500`. Publicar la unión es además lo que pone los diecisiete nombres en el contrato
generado, y con ellos el catálogo tipado del frontend.

### La bandeja en la web

Campana con contador en el `Topbar` de las tres shells autenticadas —`WorkspaceShell`,
`CleanerShell` y `TechnicianShell`—, nunca en `PublicShell` ni en `GuestShell`, que no llevan
JWT. Abre un panel `Sheet` mobile-first: listado paginado, los tres estados explícitos, acuse
al abrir una fila y «marcar todas como leídas». **No es una ruta**, y por eso la campana cuesta
un componente y no tres — cada grupo de rutas admite un juego de roles distinto.

Las filas se pintan desde `notification_type` traducido a ES/EN, **nunca desde
`subject`/`body`**, que están escritos en inglés, para un operador, y llevan UUID en crudo. Un
tipo que la interfaz no conozca cae en un texto genérico traducido.

Una fila enlaza sólo donde hay página viva: en `workspace`, `incident`, `conversation` y
`reservation`. `cleaning_task` no enlaza —no hay detalle de manager— y en las shells de campo
no enlaza nada hasta que `cleaner-app` y `tech-app` entreguen sus detalles. Sin destino, la fila
se pinta sin enlace y **sin enseñar el identificador**.

### Cuando algo no llega

`last_error` guarda la forma estructurada `{"code": ..., "channel": ..., "attempt": n}` — nunca
el texto del proveedor, porque un SDK suele devolver incrustado el mensaje que no pudo enviar.
Los códigos: `ADAPTER_ERROR`, `INVALID_RECIPIENT`, `TIMEOUT`, `NO_ADAPTER_FOR_CHANNEL`,
`MAX_ATTEMPTS_EXCEEDED`.

Ajustes en `.env`: `NOTIFICATION_MAX_ATTEMPTS` (3) y `NOTIFICATION_BATCH_SIZE` (100). No hay
backoff configurable — no hay columna donde guardar el próximo intento, y añadirla para un
logger de consola sería esquema inventado por adelantado.

## Accesos

**AutoHostAI no controla la cerradura.** PRD §15 es explícito: GrinPass importa la reserva del
PMS y crea el código él mismo. Lo que llevamos aquí es el registro de en qué estado está el
acceso de cada estancia, y quién es responsable de él.

```
GET  /api/v1/access-records?reservation_id=…&property_id=…&status=…
GET  /api/v1/access-records/{id}
POST /api/v1/access-records/{id}/manual-code   {"code": "...", "notes": "..."}
POST /api/v1/access-records/{id}/external      {"notes": "..."}
POST /api/v1/access-records/{id}/delivered
```

Estados y quién los mueve:

```
PENDING ──manual-code──► MANUAL_ADDED ──delivered──► DELIVERED
        └─external─────► CREATED_EXTERNAL ─delivered─┘
        (cualquiera) ──reserva cancelada──► REVOKED
        (con código) ──valid_to pasado────► EXPIRED
```

Cualquier otra transición responde `409`. El registro `PENDING` **no lo crea nadie a mano**:
lo pone `provision_access_records` para cada reserva confirmada.

### El código en claro no se guarda

Se introduce por `manual-code`, se reduce a `****XX` y se descarta. No hay columna para el
valor completo y no se va a añadir: nadie en el MVP lo necesita, porque quien se lo entrega al
huésped es el proveedor. `DELIVERED` es el operador confirmando que el huésped ya lo tiene.

Permisos: el **owner** ve, el **manager** opera. Limpiadora y técnico no tienen ni lo uno ni lo
otro — el código de un huésped no es parte de limpiar ni de reparar.

## Registro legal (SES.Hospedajes)

**No hay submission real** y no la va a haber en el MVP (PRD §29). Lo que existe es la capa
operativa completa detrás de `MockSESHospedajesAdapter`, para que conectar el proveedor real
sea un cambio de cableado.

Flujo de PRD §17:

1. Reserva confirmada → `provision_access_records` la pone en `PENDING_GUEST_DATA`.
2. Un manager introduce los datos del documento:
   `PATCH /api/v1/guests/{id}/document` con `nationality`, `date_of_birth`, `document_type`,
   `document_number`, `document_expiry_date` y, opcionalmente, el `reservation_id` de la
   estancia a reevaluar.
3. Con los ocho campos de §17 completos (los seis del huésped más las dos fechas de la
   reserva) el estado pasa a `READY_TO_SUBMIT`.
4. `POST /api/v1/reservations/{id}/legal-registration/submit` → `SUBMITTED`.
5. Si falla → `FAILED` y aviso en cola a los managers.

### Protección de datos

- El número se cifra en reposo con Fernet. Ningún listado lo devuelve, solo `document_status`.
- `GET /api/v1/guests/{id}/document` es el **único** endpoint que devuelve el número completo.
  Está restringido a owner y manager, y **escribe la fila de `AuditLog` antes de responder**:
  una lectura que no se pudo registrar no ocurre.
- La escritura audita **qué campos** cambiaron, nunca sus valores.

### Antes de conectar Chekin

[ADR 0006](adr/0006-pms-channel-manager-provider.md) decisión 4 elige Chekin (~3,95 €/vivienda
/mes). Adoptarlo lo convierte en **sub-encargado de datos personales**: se le envían el número
de documento y la fecha de nacimiento. Antes de integrarlo de verdad hacen falta DPA, política
de retención, comprobación de qué PII sale de verdad, y aplicar la regla 12 de
`steering/security.md` a sus webhooks `PoliceRegistration.*`, que son un segundo endpoint
entrante sin firma sobre datos de registro policial. Nada de eso está hecho.

## Entradas de roadmap relacionadas

- `guest-portal-api` — la captura de los datos por el propio huésped (token web, check-in).
- `cleaner-app` / `dashboard-web` — las pantallas que consumen todo esto.
- `hardening-release` — SMTP y WhatsApp reales, settings de integraciones.
- `maintenance` — **ya aterrizó** (2026-08-15) y usó esta maquinaria en lugar de construir una
  segunda: `TECHNICIAN_ASSIGNED` abre su plazo de SLA según la severidad de la incidencia y escala
  al `PROPERTY_MANAGER` si nadie lo atiende. `OWNER_APPROVAL_REQUIRED` viaja **sin plazo y sin
  escalado a propósito**: no hay plazo que reclamarle a una propietaria.
- `revenue` — los tipos de notificación que todavía no tienen escalado definido.
