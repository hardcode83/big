# Administración de usuarios y configuración del tenant

Cómo se opera. El *qué hace* está en las specs EARS de `sdd/specs/user-management.md`; la
autenticación que hay debajo, en [`auth-tenancy.md`](auth-tenancy.md).

## Los ocho endpoints

Todos bajo `/api/v1/`, con el sobre de error `{"error": {"code", "message", "details"}}` de
PRD §23 y `Authorization: Bearer <access_token>`.

| Método | Ruta | Quién | Respuesta |
|---|---|---|---|
| `GET` | `/users` | propietario, manager | `200` con `{data, total, page, per_page, total_pages}` |
| `POST` | `/users` | propietario | `201` con el usuario **y su contraseña temporal** |
| `GET` | `/users/{id}` | propietario, manager | `200` |
| `PATCH` | `/users/{id}` | propietario | `200` con el usuario actualizado |
| `DELETE` | `/users/{id}` | propietario | `204` (baja lógica) |
| `POST` | `/users/{id}/reset-password` | propietario | `200` con la contraseña temporal nueva |
| `GET` | `/tenants/{id}` | propietario, manager | `200` con la config anidada |
| `PATCH` | `/tenants/{id}` | propietario | `200` |

«Propietario» es `TENANT_OWNER` y «manager» es `PROPERTY_MANAGER`. `CLEANER`, `TECHNICIAN` y
`SUPER_ADMIN` reciben `403` en todos: su autoservicio es `GET /api/v1/auth/me`. El manager lee
pero no muta, porque quien asigna roles puede escalar privilegios.

El contrato navegable está en `/docs`.

## Dar de alta a alguien

```bash
curl -sS -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Ana Ruiz","email":"ana@example.com","role":"CLEANER"}'
```

La respuesta trae `temporary_password`. **Es la única vez que se puede leer**: no se guarda en
claro en ningún sitio, no aparece en los logs, no está en el rastro de auditoría y ningún `GET`
la devuelve. Si se pierde, no se recupera — se genera otra con el endpoint de reset.

Cómo comunicarla: por el canal que ya se use con esa persona (WhatsApp, SMS, en mano). El
alfabeto no tiene caracteres ambiguos —sin `0`/`O` ni `1`/`l`/`I`— precisamente porque esta
cadena se dicta o se copia a mano.

Roles disponibles: `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`. `SUPER_ADMIN`
**no se puede asignar** por la API y responde `422`: sus capacidades en PRD §6 son globales, no
operativas de un tenant, y lo cross-tenant está diferido a la fase SaaS.

Si la dirección ya existe —en este tenant o en cualquier otro— la respuesta es `409`. El email
identifica la cuenta en toda la instalación desde
[ADR 0005](adr/0005-global-email-uniqueness.md), así que no puede repetirse.

## Cuando alguien pierde su contraseña

```bash
curl -sS -X POST http://localhost:8000/api/v1/users/$USER_ID/reset-password \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Devuelve una temporal nueva, invalida la anterior y **cierra todas las sesiones abiertas de esa
persona**: sus tokens de refresh quedan revocados con razón `PASSWORD_RESET`, así que tendrá
que entrar de nuevo. Un reset que dejara vivas las sesiones anteriores no recuperaría la
cuenta, solo añadiría una credencial más.

Este endpoint no está en la lista de PRD §23. Es una adición deliberada: la recuperación
autoservicio (`/forgot-password`) es opcional en PRD §24 y depende del `NotificationAdapter`,
que llega con `access-notifications`. Sin esto, el MVP no tendría **ninguna** vía de
recuperación.

## Cambiar un rol, suspender, dar de baja

```bash
# cambiar el rol
curl -sS -X PATCH http://localhost:8000/api/v1/users/$USER_ID \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"role":"TECHNICIAN"}'

# suspender sin borrar
curl -sS -X PATCH http://localhost:8000/api/v1/users/$USER_ID \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"SUSPENDED"}'

# baja
curl -sS -X DELETE http://localhost:8000/api/v1/users/$USER_ID \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Qué esperar:

- **El `DELETE` no borra la fila**, la pasa a `INACTIVE`. El rastro de auditoría y el timeline
  apuntan a ese usuario, y borrarlo destruiría lo que la regla 9 de `steering/security.md`
  obliga a conservar. Repetirlo responde `204` otra vez, sin registrar un segundo cambio.
- **Desactivar o suspender cierra las sesiones** de esa persona (razón `USER_DEACTIVATED`).
  Hace falta: `POST /api/v1/auth/refresh` no revalida el estado de la cuenta, así que sin la
  revocación seguiría emitiendo tokens nuevos durante los 7 días de vida del refresh.
- **Nadie puede cambiar su propio rol ni su propio estado** (`422`), ni darse de baja. Una
  autodegradación dejaría al tenant sin quien lo administre y no hay endpoint de vuelta.
- **No se puede dejar el tenant sin un `TENANT_OWNER` activo** (`422`).
- Solo se escriben las columnas que cambian de verdad. Un `PATCH` con los valores que ya tenía
  responde `200` y no deja registro de auditoría: `audit_logs` es evidencia de cambios, no de
  peticiones.

## Configuración del tenant

```bash
curl -sS http://localhost:8000/api/v1/tenants/$TENANT_ID \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

El tenant y su configuración son **un solo recurso**, con la config anidada bajo `config`.

| Ajuste | Qué controla |
|---|---|
| `owner_approval_threshold_eur` | El umbral por encima del cual un gasto necesita la aprobación del propietario (principio 4 de `steering/product.md`). Por defecto 100 €. |
| `ai_confidence_threshold` | Por debajo de esta confianza, la IA escala a una persona en vez de responder. Entre 0 y 1, dos decimales. |
| `sla_*_minutes` | Minutos de SLA por severidad de incidencia. Todos deben ser positivos. |
| `checkin_window_hours_before` | Cuántas horas antes de la entrada la vivienda pasa a la ventana de check-in. |
| `checkout_ready_hours_after` | Cuántas horas después de la salida se considera lista. |
| `auto_create_cleaning_task` | Si una salida genera automáticamente su tarea de limpieza. |
| `cleaning_photo_required` | Si la limpiadora debe subir fotos para cerrar la tarea. |
| `notification_email_enabled` / `notification_whatsapp_enabled` | Canales de notificación activos. |
| `timezone` | Zona IANA con la que se calculan las ventanas de check-in y checkout. |
| `country`, `default_language`, `name`, `billing_email` | Datos del tenant. |

Dos campos se leen pero **no se pueden cambiar** por aquí, y responden `422`:

- **`status` del tenant.** Suspenderse a sí mismo deja a *todos* sus usuarios en `401` sin vía
  de vuelta, porque la autenticación revalida en cada petición que el tenant siga `ACTIVE`.
  Cambiar el estado de un tenant es una operación de plataforma.
- **`storage_type` de la configuración.** Cambiarlo apunta las fotos ya subidas a un backend
  que no las tiene, y elegir `S3` sin credenciales rompe las subidas. Pertenece a `cleaning`,
  con su migración de datos.

Pedir `/tenants/{id}` con un id que no sea el propio responde `404`, igual que un id
inexistente: la respuesta nunca confirma que otro tenant existe.

## El rastro de auditoría

Toda mutación escribe una fila en `audit_logs`, en la misma transacción que el cambio: si falla
el registro, el cambio no se aplica.

| `action` | Cuándo |
|---|---|
| `USER_CREATED` | alta de usuario |
| `USER_UPDATED` | edición que no toca el rol |
| `USER_ROLE_CHANGED` | edición que toca el rol (aunque cambie más campos) |
| `USER_DEACTIVATED` | baja |
| `USER_PASSWORD_RESET` | reset de contraseña |
| `TENANT_UPDATED` | cambio en el tenant |
| `TENANT_CONFIG_UPDATED` | cambio en la configuración |

Un cambio de rol tiene su propia acción para que la regla 9 de `steering/security.md`
(«AuditLog para … roles de User») se compruebe filtrando por `action`, con índice, en vez de
con una consulta JSONB.

Consultar el historial de una persona:

```sql
SELECT created_at, action, changes
  FROM audit_logs
 WHERE tenant_id = :tenant_id AND entity_type = 'USER' AND entity_id = :user_id
 ORDER BY created_at DESC;
```

La columna `changes` guarda `{campo: {"old": …, "new": …}}`. **Nunca guarda un valor sensible**:
una contraseña aparece como `{"password": {"changed": true}}` y nada más. No es una convención
— la única forma de construir esos diffs rechaza cualquier otra cosa.

`audit_logs` es append-only: ninguna ruta de la API la edita ni la borra.

## Limitaciones asumidas

Tres cosas que este change **no** hace, con su motivo:

1. `ASSUMPTION`: **la contraseña temporal no se fuerza a cambiar en el primer login.** Sobrevive hasta que un
   administrador la rote. Forzarlo exige una columna nueva (`must_change_password`) y un
   endpoint de cambio por el propio usuario, que pertenecen a `auth-account-recovery`.
2. `ASSUMPTION`: **`country` se valida solo de forma** (dos letras ASCII), no contra la lista ISO-3166-1 real:
   eso exigiría una dependencia nueva. `ZZ` pasa. Lo mismo aplica al formato de los emails, que
   no es RFC 5322 — captura los errores que se cometen al teclear, no todos los posibles.
3. `EXTERNAL_DEPENDENCY`: **estos endpoints no tienen salida a internet todavía.** El túnel de Cloudflare enruta solo
   al frontend, así que en el entorno dev se verifican por túnel SSH
   (`infra/environments/dev/RUNBOOK.md` §7.4) o en local. Lo cambia `api-ingress-routing`.

## Cómo se prueba en local

```bash
make up
make bootstrap          # crea el tenant inicial y sus dos usuarios
# login con BOOTSTRAP_OWNER_EMAIL / BOOTSTRAP_OWNER_PASSWORD para obtener el token
docker compose exec backend uv run pytest tests/auth/ tests/tenants/ tests/audit/ -q
```
