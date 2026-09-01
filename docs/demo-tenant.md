# El tenant de demostración — `AutoHostAI Demo`

Un segundo tenant en el entorno `dev`, con cuatro cuentas de credenciales **publicables** y un
reset diario que lo devuelve a su estado inicial con las fechas del día. Existe para poder enseñar
el producto a alguien de fuera sin darle las llaves del entorno de trabajo del equipo.

**El *qué hace* está en `sdd/specs/demo-tenant.md`; aquí va el *cómo se usa y se opera*.**

## Dónde vive, y qué lo separa del tenant del equipo

Vive en `dev` (https://autohostai.digitalsec.work), en **la misma VM, la misma base de datos y el
mismo bucket** que `AutoHostAI Dev`, el tenant que usa el equipo. Un entorno propio para la demo
está explícitamente fuera de alcance.

Así que la separación es **una sola y hay que nombrarla**: el aislamiento por tenant. Ninguna de
las cuatro cuentas publicadas puede leer ni escribir una fila de `AutoHostAI Dev`, y la visibilidad
cross-tenant del `SUPER_ADMIN` sigue cerrada (entrada de roadmap `saas-cross-tenant`, sin empezar).
El comando de reset se acota igual: su tenant es una **constante del módulo**
(`app/cli/demo_reset.py`), no un parámetro, así que no existe ningún `-e` ni argumento por el que
pueda apuntar al tenant del equipo.

## Las cuatro cuentas

Una sola contraseña para las cuatro, la misma siempre, y **restaurada en cada reset** aunque un
visitante la haya cambiado. Las cuentas quedan operativas al instante: no hay cambio de contraseña
forzado.

| Cuenta | Rol | Qué puede hacer |
|---|---|---|
| `owner@demo.autohostai.test` | `TENANT_OWNER` | Lee reservas, viviendas, limpiezas, incidencias y conversaciones; **gestiona** usuarios, ajustes del tenant, plantillas de limpieza, reglas de precios y recomendaciones; responde las dos puertas de aprobación de coste de una incidencia; acuña enlaces de portal. **No** opera limpiezas ni hace triaje de incidencias |
| `manager@demo.autohostai.test` | `PROPERTY_MANAGER` | El día a día: opera reservas, viviendas, limpiezas (asignar, reasignar, validar), triaje y asignación de incidencias, conversaciones, accesos y el registro legal, reglas de precios |
| `cleaner@demo.autohostai.test` | `CLEANER` | Su autoservicio y **ejecutar** limpiezas: aceptar, empezar, marcar checklist, subir fotos, cerrar. Nada más |
| `technician@demo.autohostai.test` | `TECHNICIAN` | Su autoservicio y **ejecutar** incidencias: aceptar, ponerse en camino, trabajar, resolver. Solo las asignadas a él |

**La contraseña no está en este documento, ni en ningún otro fichero del repositorio.** Vive sólo
en el OCI Vault (`autohostai-dev-demo-account-password`); en local la pones tú en tu `.env`. El
comando nunca la imprime, el workflow la enmascara en cuanto la lee, y un fallo de base de datos
imprime **sólo la clase** de la excepción precisamente para que su detalle —que anexa la sentencia
con sus parámetros, y entre ellos un hash de bcrypt— no acabe en un log. Cómo cambiarla: más abajo.

## Qué NO es demostrable todavía

Esto es la mitad importante del documento: **la mayor parte de las rutas de la aplicación existe
como placeholder**, y una demo que las anuncie decepciona. Lo que hay hoy:

| Ruta | Estado | Su casa |
|---|---|---|
| `/conversations` | placeholder | `conversations-inbox` |
| `/pricing` | placeholder | `pricing-web` |
| `/cleaner`, `/cleaner/tasks/[id]` | placeholder | `cleaner-app` |
| `/reviews` | placeholder, y **tampoco hay backend**: `app/reviews/` tiene entidades y modelos, ni capa de aplicación ni router | `revenue-reviews` |
| `/statements`, `/approvals` | placeholder | `revenue-statements` |
| `/settings`, `/settings/integrations` | placeholder | pendiente |
| `/forgot-password` | placeholder | `auth-account-recovery` (los endpoints existen; la pantalla no) |

Dos consecuencias que conviene decir en voz alta antes de una demo:

- **La cuenta `CLEANER` no es un recorrido demostrable.** Se crea porque el dataset la necesita
  —la limpieza cerrada es *de* la limpiadora—, pero sus dos pantallas son placeholders. Su trabajo
  se ve **desde la cuenta del manager**, en `/cleaning`, que sí está construida. La cuenta
  `TECHNICIAN` **sí lo es** desde `tech-app`: entra en `/tech`, ve su incidencia asignada con la
  vivienda, la abre y recorre el ciclo. Lo que se enseñe la mueve de verdad, así que conviene
  hacerlo al final de la demo o resetear después. El recorrido se ha hecho de punta a punta en un navegador
  contra un backend vivo (2026-08-29): aceptar, ponerse en ruta, subir una foto de antes y otra de
  después, y cerrar con coste y materiales.
- **`AuthGuard` no distingue rol**: comprueba que hay sesión y nada más. Así que cualquiera de las
  cuatro cuentas puede abrir cualquier ruta del workspace, y lo que la frene será el `403` del
  backend, no la navegación. No es un defecto de la demo, es el estado de la ruta.

**Lo que sí se recorre entero**, y es lo que hay que enseñar: `/dashboard`, `/timeline`,
`/properties` y el detalle de una vivienda, `/reservations` y el detalle de una estancia,
`/cleaning`, `/incidents` y el detalle de una incidencia, la **app del técnico** (`/tech` y el
detalle de una incidencia desde la cuenta `TECHNICIAN`), y el **portal de huésped**
(`/guest/[token]`), que es la única superficie que se ve sin cuenta.

Qué contiene el dataset, con sus tres rarezas que no son defectos:
[`seed-demo.md`](seed-demo.md).

## El enlace del portal de huésped

Cada reset acuña un enlace nuevo para la estancia activa y **revoca el anterior**. Es la única
credencial que el comando emite a propósito: su valor en claro existe una sola vez —de la fila sólo
se guarda su digest—, así que no imprimirlo es perderlo.

- En el comando sale por la salida estándar:
  `demo_reset: guest portal for the active stay: https://…/guest/<token>`
- En el workflow se publica en el **resumen del job**, y **no** se enmascara: el `::add-mask::`
  cubre la contraseña y sólo la contraseña.
- `make seed-demo` **no** emite ninguno: su recuento sale como `0 guest_access_tokens`. El enlace
  es cosa del reset, porque es lo que lo puede acuñar de cero cada vez.

## Resetear a mano

En el entorno desplegado, por `workflow_dispatch` — sólo sobre `main`, que es donde el job se
acota:

```bash
gh workflow run demo-reset.yml --ref main
```

En un stack local, con `DEMO_ACCOUNT_PASSWORD` puesta en tu `.env`:

```bash
make demo-reset
```

**La cadencia programada es diaria, 03:15 UTC.** Fuera de la hora en punto porque GitHub encola ahí
los cron y **la hora no es exacta**; y lejos de las 06:00 UTC, cuando el beat corre
`generate_price_recommendations`. Tres cosas que conviene saber de ese `schedule:`:

- **Se desactiva tras 60 días sin actividad en el repositorio.** Si la demo deja de refrescarse y el
  workflow no aparece ni en rojo ni en verde, es esto. `workflow_dispatch` lo reactiva.
- Comparte `concurrency: deploy-dev` con el job `deploy`, así que **espera** si hay un despliegue en
  curso en vez de correr encima de un `.env` a medio reescribir.
- Con el runner de la VM caído, el job **queda en cola**, no falla.

Lo que un visitante acumule vive por tanto menos de 24 h, y eso es parte de la contención de tener
credenciales publicadas: no hay cuotas por cuenta.

## Cambiar la contraseña de demostración

El valor lo pone **una persona, out-of-band**, en el OCI Vault. Terraform declara el secreto y lo
crea con un `random_password` inerte —para que un entorno recién aplicado tenga credenciales que
nadie conoce en vez de credenciales conocidas—, y `lifecycle { ignore_changes = [secret_content] }`
es lo que hace que el valor que pongas sobreviva al `apply` siguiente.

**Forma acordada**: una frase corta y dictable por teléfono, del orden de 15 caracteres con guiones.
Tiene que estar **por encima de `PASSWORD_MIN_LENGTH` (12)**, y no por formalismo: por debajo de ese
umbral el propio sistema rechazaría que un visitante volviera a fijarla desde
`POST /auth/change-password`, así que la cuenta que alguien cambiase quedaría con una contraseña que
nadie conoce hasta el reset siguiente.

```bash
# Desde tu portátil con el perfil de OCI configurado; en la VM, añade --auth instance_principal.
SECRET_ID="$(oci vault secret list --compartment-id "$COMPARTMENT_OCID" \
  --query "data[?\"secret-name\"=='autohostai-dev-demo-account-password'].id | [0]" --raw-output)"

oci vault secret update-base64 --secret-id "$SECRET_ID" \
  --secret-content-content "$(printf '%s' 'tu-frase-con-guiones' | base64)"
```

**`printf` y no `echo`**: `echo` añade un salto de línea que se codifica *dentro* de la contraseña y
produce una credencial que no coincide con lo que escribiste.

**Y qué hay que ejecutar para que surta efecto: el reset.** El Vault es de dónde la lee el workflow,
no dónde la usan las cuentas. Hasta el reset siguiente —el de las 03:15 UTC, o el que dispares a
mano— las cuatro cuentas siguen con la contraseña anterior. El reset la converge sobre las cuatro,
revoca sus sesiones vivas y limpia su bloqueo de login.

> **Verificación pendiente antes de publicar credenciales a nadie.** Que el provider de OCI respete
> `ignore_changes` sobre `secret_content` está por comprobar, y de ello depende todo lo anterior: si
> no lo respeta, cada `terraform apply` devuelve el secreto al valor de `random_password`, el reset
> siguiente lo propaga a las cuatro cuentas y **las credenciales publicadas dejan de funcionar en
> silencio**. Se comprueba con el valor ya puesto: un `terraform plan` que **no** proponga cambios
> en `demo_account_password` significa que aguanta. Si propusiera reescribir `secret_content`, el
> procedimiento de arriba no vale y la salida escrita es otra: la contraseña publicada pasa a ser la
> que genera `random_password` —leída del Vault— y rotarla es
> `terraform apply -replace=random_password.demo_account`.

## Cuando se rompe

Códigos de salida del comando, que es lo que el workflow lee:

| Código | Qué significa |
|---|---|
| 0 | Reseteado. La salida son recuentos por entidad y las fases recorridas |
| 1 | **Nada escrito**: falta `DEMO_ACCOUNT_PASSWORD` o tiene menos de 12 caracteres, o el comando **refusó** |
| 2 | Fallo dentro de una fase, **nombrándola**, y sin cambios parciales en la base. Imprime sólo la clase de la excepción; el detalle está en los logs del stack |

Las diez fases, en orden, son las que aparecen en esa salida:
`configuration → refusal → prepare → bootstrap → scope → delete → converge → seed → storage-sweep
→ clear-lock`. Las dos últimas van **después** del commit y no pueden poner el comando en rojo: si
el almacén de objetos o Redis fallan, la base ya quedó consistente y se informa con una nota.

| Síntoma | Qué pasó | Arreglo |
|---|---|---|
| Rojo con `refusal: … its billing address is not billing@demo.autohostai.test`, y «nada escrito». La demo deja de refrescarse y el dataset envejece | **Un visitante cambió `billing_email` del tenant.** El `TENANT_OWNER` publicado tiene `MANAGE_TENANT_SETTINGS`, así que puede hacerlo desde `PATCH /tenants/{id}`, y esa dirección es la marca por la que el comando reconoce que el tenant es el suyo. Es un **límite aceptado**, no un descuido: falla **cerrado**, que es lo correcto ante un tenant que no se puede identificar | Devolver `billing_email` a `billing@demo.autohostai.test` con `PATCH /api/v1/tenants/{id}` |
| Rojo en la fase `bootstrap` con `BootstrapConflictError` | **Renombraron el tenant.** El comando no encuentra el suyo, `bootstrap.apply_plan` intenta crear uno nuevo y choca con la unicidad **global** del correo. No commitea nada | Devolver `name` a `AutoHostAI Demo` |
| `precondición: el entorno no está desplegado` | No hay `.env` en el workspace del runner, o `postgres` no está corriendo | Lanzar `deploy-dev` primero |
| `no se pudo leer del Vault el secret requerido: DEMO_ACCOUNT_PASSWORD` | El secreto no existe con ese nombre, o su OCID no está en la política que lo hace legible por el dynamic-group del runner | Aplicar `infra-dev` |
| Las cuatro cuentas no dejan entrar durante 15 minutos | **Diez intentos fallidos bloquean una cuenta**, y con credenciales publicadas cualquiera puede hacerlo con ~40 intentos, indefinidamente. Sólo afecta a disponibilidad, y es un límite aceptado | Esperar la ventana, o disparar un reset: `clear-lock` limpia el cerrojo de las cuatro |
| Nota `storage-sweep: could not delete …` o `skipped … no usable store` | El reset borró las filas y no pudo borrar los objetos que colgaban de ellas. **El comando sale 0**, porque la base quedó consistente | Borrar esas claves del bucket a mano cuando estorben |
| Nota `the login lockout of N account(s) could not be cleared (Redis unreachable)` | Igual: el reset salió bien, sólo quedó el cerrojo | Nada. Expira solo dentro de su ventana |
| Nota `tenant timezone was '…'; restored to 'Europe/Madrid'` (o `country`) | Un visitante movió esa columna. `timezone` es la que importa: **ancla las fechas de todo el dataset**, así que sin restaurarla cada reset fecharía la demo en un día que una siembra desde cero nunca produce, informando de éxito | Nada. El reset ya la restauró, y la nota dice qué valor había |

## Qué NO queda como recién sembrado

El reset promete un estado «indistinguible de un aprovisionamiento desde cero ese mismo día», y eso
se lee sobre **lo que la API y las pantallas devuelven**: la composición del dataset, los estados
operacionales, el timeline y las fechas. Cuatro cosas quedan fuera, y conviene tenerlas presentes:

- **`audit_logs`** de los últimos **7 días**, que se conservan a propósito. Pasado ese plazo, la
  fase `purge-audit` del comando los borra al final del reset (ver «Retención del `audit_logs`»
  abajo). La fila del propio purgado —una por ejecución, con `action='AUDIT_LOG_PURGED'` y
  `entity_type='AUDIT_LOG'`— se queda dentro de la ventana, así que la huella del último borrado
  es lo último que desaparece.
- **`users.created_at` y `users.id`** de las cuatro cuentas: las filas se conservan porque la
  contraseña se **converge** en vez de recrearse.
- **`users.last_login_at`**: cada login de un visitante la mueve, cualquier lector con
  `MANAGE_USERS` la ve, y el reset **no la restaura** — está en la lista de columnas que ninguna
  escritura ordinaria puede tocar, a propósito, para que nadie pueda falsificar historial de acceso.
  Así que un visitante puede leer cuándo estuvo el anterior. Se acepta: es un timestamp no sensible,
  visible sólo dentro del tenant de demostración y sólo para quien ya tiene las credenciales
  publicadas.

Lo que **sí** se restaura de esas cuatro filas, y no es cosmético: la contraseña, el rol, el estado,
y el `name` y el `phone` — que son el único canal de desfiguración duradera del tenant, porque
`PATCH /users/{id}` los acepta de quien tenga `MANAGE_USERS` y son el único contenido escribible por
un visitante que el reset conserva.

## Retención del `audit_logs`

El `audit_logs` del tenant demo es la **única** tabla nightly-reset que nunca se vacía: se conserva
porque el registro de auditoría es valioso, y porque cada reset añade filas de convergencia (una
por cuenta convergida) más las del propio purgado. Sin un corte, crece sin límite — y por eso el
comando aplica una retención.

- **Periodo**: 7 días. La constante `DEMO_AUDIT_RETENTION_DAYS` vive en `backend/app/cli/demo_reset.py`,
  junto a `DEMO_TENANT_NAME` y la política de contraseñas; no está en `Settings`, no es variable de
  entorno, no es columna de base de datos. Es una decisión de ingeniería, no de despliegue.
- **Cuándo corre**: durante el reset diario, en la fase `purge-audit` (entre `storage-sweep` y
  `clear-lock`), fuera de la transacción. Si falla, el reset sigue verde y se reporta como una
  nota con la forma `purge-audit: failed with <ClassName> (detail withheld on purpose)`.
- **Qué preserva**: por construcción del corte, **las filas del último reset** (sus `created_at`
  caen dentro de la ventana de 7 días). Lo que se borra es el histórico más antiguo — típicamente la
  acumulación de resets anteriores.
- **Auditoría del propio purgado**: antes del `DELETE`, la fase escribe una fila en `audit_logs` con
  `action='AUDIT_LOG_PURGED'`, `entity_type='AUDIT_LOG'`, `entity_id` derivado deterministamente
  del tenant id (`uuid.uuid5(tenant_id, "demo-audit-purge")`) y `actor_user_id=None` — un comando
  CLI no tiene identidad que registrar. La fila pasa por `AuditLogFactory.build` + `ChangeSet`,
  así que la regla 11 de seguridad se cumple por construcción.
- **Cómo se ve el histórico más antiguo**: la única forma soportada es **descargar la fila antes
  del siguiente reset** — no hay endpoint, ni vista, ni exportación automática. La retención
  borra lo que la demo no necesita mantener; quien necesite auditoría histórica tiene que sacarla
  por su cuenta, y la ventana de 7 días es la holgura con la que cuenta.

## Ver también

- [`seed-demo.md`](seed-demo.md) — el dataset, qué siembra y qué deja fuera
- [`guest-portal.md`](guest-portal.md) — cómo se opera el enlace del huésped y qué ve
- [`auth-tenancy.md`](auth-tenancy.md) — el límite de intentos de login y su configuración
- `infra/environments/dev/RUNBOOK.md` §10 — la rotación de la contraseña en el Vault
