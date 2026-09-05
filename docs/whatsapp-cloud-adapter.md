# WhatsApp Cloud API

Cómo se **opera** la conexión de un tenant a WhatsApp: qué variables de entorno hacen falta, cómo
se registra el webhook en el panel de Meta y cómo se asocia el número de un tenant. El *qué hace*
el sistema vive en `sdd/specs/whatsapp-cloud-adapter.md` (lo escribe la fase de archivado); aquí va
el *cómo se trabaja con ello*.

Lo primero, porque cambia cómo se lee todo lo demás: **una sola App de Meta sirve a toda la
plataforma**. A diferencia de los webhooks de PMS (`docs/reservations-webhooks.md`), donde cada
tenant tiene su propio endpoint y sus propios secretos, Meta solo permite una URL de webhook y un
App secret por App — así que el token/secreto por tenant no existe aquí. Lo único que cada tenant
aporta es su propio `phone_number_id` de WhatsApp Business bajo esa misma App.

## Variables de entorno (una vez, para toda la plataforma)

Sin valor en `.env.example` (regla 8 de `sdd/steering/security.md`) — el valor real vive solo en el
entorno del despliegue:

| Variable | Qué es |
|---|---|
| `WHATSAPP_PROVIDER` | `mock` (comportamiento actual, sin credenciales) o `meta` (Cloud API real). En blanco se resuelve a `mock`. |
| `WHATSAPP_ACCESS_TOKEN` | Bearer token de la Graph API (token de usuario del sistema en producción). Obligatorio con `WHATSAPP_PROVIDER=meta`. |
| `WHATSAPP_PHONE_NUMBER_ID` | El identificador Graph API del número por defecto de la plataforma (el "from" de notificaciones proactivas sin conversación de huésped detrás). Obligatorio con `meta`. |
| `WHATSAPP_APP_SECRET` | Clave HMAC (`X-Hub-Signature-256`) con la que se verifica la firma de cada webhook entrante. Obligatorio con `meta`. |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | Secreto de un solo uso para el handshake de verificación de Meta (ver abajo). Sin él, Meta se niega a guardar la suscripción del webhook. |

**El coste declarado de una App compartida**: al no haber secreto por tenant, una fuga de
`WHATSAPP_APP_SECRET` permite falsificar una entrega firmada válida para **todos** los tenants a la
vez, no solo uno — a diferencia de `reservations-webhooks`, donde cada tenant acota su propio radio
de daño. Es el precio de la topología de Meta, no una elección de este sistema (Meta no ofrece un
secreto por número). No hay rotación automatizada todavía: rotar hoy significa actualizar el panel
de Meta y el secreto del despliegue a la vez, con una ventana en la que las entregas firmadas con el
secreto viejo se rechazan.

## Registrar el webhook en el panel de Meta (una vez, para toda la plataforma)

1. En el panel de la App de Meta (WhatsApp → Configuration), pega la URL fija del webhook:
   `https://<host>/api/v1/webhooks/whatsapp` (no lleva segmento por tenant — no hay nada que poner
   ahí).
2. En **Verify token**, pega el mismo valor que `WHATSAPP_WEBHOOK_VERIFY_TOKEN`.
3. Al guardar, Meta llama una vez a `GET /api/v1/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...`.
   Si el token coincide, el endpoint devuelve `hub.challenge` en texto plano y Meta guarda la
   suscripción; si no coincide (o falta), responde `403` sin cuerpo y Meta **no guarda nada** — es
   un fallo de configuración, no un mensaje perdido.
4. Suscribe el campo `messages` del producto WhatsApp Business Account para que Meta empiece a
   entregar mensajes entrantes a esa URL.

## Asociar el número de un tenant

Lo hace el **`TENANT_OWNER`** (permiso `MANAGE_TENANT_SETTINGS`) — decide qué número de WhatsApp se
trata como el de ese tenant, para todas sus viviendas a la vez:

```bash
curl -X POST https://<host>/api/v1/messaging/whatsapp-phone-number \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number_id": "<id de Graph API del número de WhatsApp Business del tenant>",
    "display_phone_number": "+34 600 000 000",
    "default_property_id": "<uuid de una vivienda de este tenant>"
  }'
```

- `phone_number_id` lo aporta el operador — nunca se genera aquí — y es el identificador de Meta
  del número ya dado de alta en la App (no el número visible en formato humano).
- `default_property_id` es obligatoria: es la vivienda a la que se ancla un mensaje entrante que no
  resuelve a huésped/estancia concretos (ni ese hilo desaparece ni el sistema inventa una
  asociación — queda visible al operador). Debe ser una vivienda propia de ese tenant.
- Asociar el mismo `phone_number_id` a un segundo tenant sin liberarlo antes del primero falla con
  `409` — nunca se sobrescribe en silencio (R6.2).
- Volver a llamar con un `phone_number_id` distinto **reemplaza** la asociación existente del
  tenant (create-or-replace, R6.1/R6.3).

Para retirar la asociación (el equivalente operativo de "rotar" en este modelo — un número que
cambia de tenant o deja de usarse):

```bash
curl -X POST https://<host>/api/v1/messaging/whatsapp-phone-number/release \
  -H "Authorization: Bearer <token>"
```

Las conversaciones ya abiertas bajo ese número quedan intactas; el número simplemente deja de
resolver a ningún tenant hasta que alguien lo asocie de nuevo. Ambas rutas quedan auditadas
(regla 9 de `sdd/steering/security.md`).

## Antes de contar con notificaciones proactivas

Todavía no existe ninguna plantilla de mensaje de WhatsApp Business aprobada. Cualquier
notificación **proactiva** (no una respuesta dentro de las 24h desde el último mensaje del
huésped) fallará con `OUTSIDE_SESSION_WINDOW` hasta que se someta y apruebe una plantilla en el
panel de Meta — un trámite externo, de duración impredecible, fuera del control de este equipo.
Responder dentro de la ventana de 24h funciona sin plantilla desde el primer despliegue.

## Modo `mock`

Con `WHATSAPP_PROVIDER=mock` (o sin establecer la variable) el sistema se comporta exactamente
como antes de esta integración: los envíos salientes quedan en un log y no se necesita ninguna de
las credenciales de arriba. Es el modo por defecto — nada se rompe en un despliegue que todavía no
ha conectado WhatsApp.
