# Runbook — sembrar y deshacer los datos de demo en `dev`

Cómo poblar el entorno `dev` con el dataset de demo, y cómo quitarlo. Complementa a
[`RUNBOOK.md`](./RUNBOOK.md) (operación general) y a la spec `sdd/specs/seed-data-demo.md`
(el contrato del comando).

Escrito el 2026-08-15 después de ejecutarlo de verdad contra `dev`, así que recoge los dos
tropiezos que la documentación anterior no anticipaba.

---

## 1. Qué es `seed_demo`, y qué no

`make seed-demo` (→ `python -m app.cli.seed_demo`) **no crea el tenant: lo completa**. Presupone
`bootstrap`, que es lo único que da la primera entrada a un entorno nuevo. Si el tenant nombrado por
`BOOTSTRAP_TENANT_NAME` no existe, aborta **sin escribir nada**.

Crea el dataset de PRD §27:

| Entidad | Cantidad | Detalle |
|---|---|---|
| `users` | 2 | las cuentas operativas `CLEANER` y `TECHNICIAN` |
| `properties` | 2 | «Redes 11» y «Pajaritos 8» |
| `guests` | 3 | |
| `reservations` | 3 | una pasada, una activa y una próxima |
| `cleaning_checklist_templates` | 1 | con seis tipos de foto: `living_room`, `bedroom`, `bathroom`, `kitchen`, `entrance`, `damage_if_found` |
| `incidents` | 3 | las tres de §27, clasificadas; la segunda asignada al técnico |
| `cleaning_tasks` | 1 | la del checkout de la estancia pasada, recorrida hasta `COMPLETED` |
| `cleaning_photos` | 6 | objetos reales en el almacenamiento que el tenant resuelva |

**Desde `seed-data-demo-extension` (2026-08-17) sí crea una tarea de limpieza, y la cierra.** Antes
sólo creaba la *plantilla*; ahora deja el dataset avanzado por sus propias vías: las dos estancias
que §27 muestra en un estado alcanzado llegan a él por sus casos de uso, el estado operacional de
las viviendas es consecuencia de la máquina de estados y no una columna escrita, y la limpieza de
la estancia pasada se recorre entera —aceptar, empezar, 18 ítems, 6 fotos, cerrar—. Consecuencias
para quien opera `dev`, las tres:

- **La demo abre con «Redes 11» en `MAINTENANCE_REQUIRED`**, porque hay un huésped dentro y una
  incidencia `ACCESS`/`HIGH` con técnico asignado. **Es correcto, no un fallo del seed**: el
  recorrido completo está en el *timeline*, y el estado operacional es la foto final.
- **Las incidencias 1 y 3 quedan en `CLASSIFIED`**, no en el `OPEN` literal de §27: `classify` es
  la única puerta de salida de `OPEN`, y el job de beat las movería igual cada cinco minutos.
- **En `dev` el comando necesita red y credenciales**, porque el tenant está en `S3` desde
  `object-storage-provisioning` y las seis fotos van por el puerto de almacenamiento. Si falta el
  bucket, la región o la credencial, aborta con **exit 1 antes de escribir nada** — ver §5.

Es idempotente: una segunda ejecución no crea ni modifica ninguna fila y sale con código 0,
imprimiendo los ocho recuentos a cero. **Tampoco vuelve a subir las fotos**, así que en el bucket
siguen siendo seis y no doce.

---

## 2. Sembrar

### El tropiezo que hay que conocer antes

El comando necesita **siete** variables de entorno, y **el `.env` de la VM no tiene ninguna**: el
deploy lo trunca y lo regenera en cada ejecución, con solo lo que la aplicación necesita en runtime.
Así que hay que pasarlas en línea.

Las siete: `BOOTSTRAP_TENANT_NAME`, `SEED_CLEANER_NAME`, `SEED_CLEANER_EMAIL`,
`SEED_CLEANER_PASSWORD`, `SEED_TECHNICIAN_NAME`, `SEED_TECHNICIAN_EMAIL`,
`SEED_TECHNICIAN_PASSWORD`. Se validan todas juntas **antes** de abrir transacción, así que si
faltan te las nombra de una vez.

⚠️ **`BOOTSTRAP_TENANT_NAME` tiene que coincidir EXACTAMENTE** con el tenant existente (hoy
`AutoHostAI Dev`). La idempotencia se ancla en ese nombre: con uno distinto no falla, **crea un
segundo tenant**.

### El procedimiento

Guarda esto como `/tmp/seed-demo-remote.sh` en la VM. La contraseña llega por **stdin**, no por
argumento, y se pasa al contenedor con `-e NOMBRE` sin `=valor` —así docker la toma del entorno del
cliente en vez de ponerla en su línea de comandos, donde cualquiera con `ps` la vería—:

```bash
#!/usr/bin/env bash
set -euo pipefail

PW="$(cat)"
[ -n "$PW" ] || { echo "error: no llegó contraseña por stdin" >&2; exit 1; }

export BOOTSTRAP_TENANT_NAME='AutoHostAI Dev'
export SEED_CLEANER_NAME='Cleaner Dev'
export SEED_CLEANER_EMAIL='josegascon+cleaner@gmail.com'
export SEED_CLEANER_PASSWORD="$PW"
export SEED_TECHNICIAN_NAME='Technician Dev'
export SEED_TECHNICIAN_EMAIL='josegascon+technician@gmail.com'
export SEED_TECHNICIAN_PASSWORD="$PW"

cd /opt/actions-runner/_work/AutoHostAI/AutoHostAI
docker compose -f docker-compose.deploy.yml exec -T \
  -e BOOTSTRAP_TENANT_NAME \
  -e SEED_CLEANER_NAME -e SEED_CLEANER_EMAIL -e SEED_CLEANER_PASSWORD \
  -e SEED_TECHNICIAN_NAME -e SEED_TECHNICIAN_EMAIL -e SEED_TECHNICIAN_PASSWORD \
  backend python -m app.cli.seed_demo
```

Y desde tu máquina, con la contraseña en un fichero de permisos `600`:

```bash
read -rs P && printf '%s' "$P" > /tmp/seedpass && unset P && chmod 600 /tmp/seedpass
scp -i ~/.ssh/autohostai_dev_vm seed-demo-remote.sh ubuntu@<ip>:/tmp/
ssh -i ~/.ssh/autohostai_dev_vm ubuntu@<ip> 'bash /tmp/seed-demo-remote.sh' < /tmp/seedpass
shred -u /tmp/seedpass
```

Salida esperada:

```
seed-demo: created 2 users, 2 properties, 3 guests, 3 reservations, 1 checklist_templates, 1 cleaning_tasks, 6 cleaning_photos, 3 incidents
```

Los ocho tipos se imprimen **incluso a cero**, que es lo que distingue «una segunda ejecución no
hizo nada» de «se hizo a medias». Un `0 cleaning_tasks, 0 cleaning_photos` en una **primera**
ejecución no es un fallo: significa que el checkout no aprovisionó limpieza —el tenant la tiene
desactivada o no hay plantilla de checklist— y el comando sigue adelante a propósito.

### Emails de las cuentas

Se usa plus-addressing sobre un buzón que ya existe (`josegascon+cleaner@`,
`josegascon+technician@`), igual que el manager de bootstrap. Los emails son **únicos en toda la
instalación**, así que reutilizar uno de otro tenant aborta con `BootstrapConflictError`.

---

## 3. Deshacer

**No hay comando de teardown.** `seed_demo` solo crea. Deshacer es SQL a mano, y por eso este
apartado existe.

### Antes de nada: qué se te queda fuera

**Las fotos subidas al bucket NO se borran con el SQL.** Borrar `cleaning_photos` elimina la fila,
no el objeto en `autohostai-dev-media`: el `DELETE` desde la API está fuera de alcance por decisión
del proposal de `object-storage-provisioning`, y la retención sigue sin decidirse. Quedan huérfanas
hasta que alguien las quite a mano:

```bash
oci os object list --bucket-name autohostai-dev-media --prefix tenants/
oci os object bulk-delete --bucket-name autohostai-dev-media --prefix tenants/<tenant_id>/
```

Hazlo **antes** del SQL si quieres saber qué claves borrar — después de borrar las filas ya no hay
de dónde sacarlas, y tendrás que listar el bucket a ciegas.

### El orden importa

Las claves foráneas obligan a borrar de hoja a raíz. Este es el grafo real que las gobierna:

```
cleaning_photos ─┐
cleaning_checklist_completions ─┴─> cleaning_tasks ─> cleaning_checklist_templates ─> properties
                                          └─> reservations ─> guests
                                          └─> users
```

Y hay más tablas colgando de `properties`, `reservations` y `users` de las que el seed llena
(`incidents`, `expenses`, `conversations`, `timeline_events`, `access_records`, `reviews`,
`owner_approvals`, `price_recommendations`, `pms_credentials`, `owner_statements`,
`guest_access_tokens`, `messages`, `notification_logs`, `audit_logs`, `user_sessions`,
`property_state_transitions`, `review_response_drafts`…). Si has estado usando el entorno, pueden
tener filas que apunten a lo que vas a borrar.

### El SQL

Guárdalo como fichero y pásalo por stdin — no lo metas en `psql -c` con comillas, que es donde se
tuerce el escapado:

```sql
BEGIN;

-- Ámbito: SOLO el tenant de demo. Sin este WHERE, esto es un borrado del entorno entero.
\set tenant_name 'AutoHostAI Dev'

CREATE TEMP TABLE t AS SELECT id FROM tenants WHERE name = :'tenant_name';

-- Hojas de limpieza
DELETE FROM cleaning_photos WHERE cleaning_task_id IN (
  SELECT ct.id FROM cleaning_tasks ct WHERE ct.tenant_id IN (SELECT id FROM t));
DELETE FROM cleaning_checklist_completions WHERE cleaning_task_id IN (
  SELECT ct.id FROM cleaning_tasks ct WHERE ct.tenant_id IN (SELECT id FROM t));
DELETE FROM cleaning_tasks WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM cleaning_checklist_templates WHERE tenant_id IN (SELECT id FROM t);

-- Lo que cuelga de reservations
DELETE FROM access_records     WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM guest_access_tokens WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM messages           WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM conversations      WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM reviews            WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM incidents          WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM timeline_events    WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM reservations       WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM guests             WHERE tenant_id IN (SELECT id FROM t);

-- Lo que cuelga de properties
DELETE FROM expenses                   WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM owner_approvals            WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM owner_statements           WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM price_recommendations      WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM pms_credentials            WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM property_state_transitions WHERE tenant_id IN (SELECT id FROM t);
DELETE FROM properties                 WHERE tenant_id IN (SELECT id FROM t);

-- Las DOS cuentas operativas del seed, y solo esas: el owner y el manager son de `bootstrap`
-- y borrarlos te deja sin entrada al entorno.
DELETE FROM user_sessions WHERE user_id IN (
  SELECT id FROM users WHERE email IN ('josegascon+cleaner@gmail.com','josegascon+technician@gmail.com'));
DELETE FROM password_reset_tokens WHERE user_id IN (
  SELECT id FROM users WHERE email IN ('josegascon+cleaner@gmail.com','josegascon+technician@gmail.com'));
DELETE FROM users WHERE email IN ('josegascon+cleaner@gmail.com','josegascon+technician@gmail.com');

-- Revisa el recuento ANTES de confirmar.
SELECT
  (SELECT count(*) FROM properties)   AS props,
  (SELECT count(*) FROM reservations) AS reservas,
  (SELECT count(*) FROM users)        AS usuarios;

-- COMMIT;   <- descoméntalo solo si el recuento es el que esperas
ROLLBACK;
```

**Está escrito para terminar en `ROLLBACK` a propósito.** Ejecútalo, mira el recuento, y solo
entonces cambia las dos últimas líneas. Un `DELETE` sin `WHERE` de tenant en la tabla equivocada no
tiene vuelta atrás salvo restaurando el backup.

⚠️ **`audit_logs` no se toca.** Sus filas apuntan a `actor_user_id`, así que borrar usuarios puede
chocar con esa FK. Si pasa, la decisión no es borrar la auditoría: es dejar esos dos usuarios en
paz. El registro de auditoría es justamente lo que no se borra para dejar limpio un entorno.

### La alternativa nuclear

Si el entorno no tiene nada que salvar, sale más barato y más seguro tirar la base y rehacerla:

```bash
docker compose -f docker-compose.deploy.yml down
docker volume rm <proyecto>_postgres_data
docker compose -f docker-compose.deploy.yml up -d
# y después: alembic upgrade head, bootstrap, seed-demo
```

Recuerda que eso también se lleva por delante el `storage_type = S3` del tenant, así que hay que
volver a convergerlo (RUNBOOK §9.2). Y las fotos del bucket **siguen ahí**: la base y el almacén de
objetos tienen ciclos de vida distintos, y esa es exactamente la asimetría que hay que tener
presente cada vez que se «limpia» un entorno.

---

## 4. Crear una tarea de limpieza (no la crea el seed)

Hace falta para probar la subida de fotos, y **necesita dos cuentas distintas**, que es el segundo
tropiezo que esta documentación no anticipaba:

| Paso | Permiso | Quién |
|---|---|---|
| `POST /cleaning-tasks` | `MANAGE_CLEANING_TASKS` | **PROPERTY_MANAGER** |
| `PATCH /cleaning-tasks/{id}` (asignar a la limpiadora) | `MANAGE_CLEANING_TASKS` | **PROPERTY_MANAGER** |
| `accept`, `start`, subir foto | `EXECUTE_CLEANING_TASKS` | **CLEANER**, y solo la asignada |

El `TENANT_OWNER` **no puede** crear tareas: recibe `403 FORBIDDEN`. Y el manager tampoco puede
ejecutarlas — `EXECUTE_CLEANING_TASKS` es de la limpiadora sola, y la entidad responde `404` a
cualquiera que no sea la asignada. No es un descuido de la matriz de permisos: PRD §6 reparte
*leer*, *administrar* y *hacer* entre personas distintas a propósito.

> ⚠️ **El segundo paso de esa tabla falla casi siempre, y no por permisos.** `POST /cleaning-tasks`
> (`CreateCleaningTaskUseCase`) **no toca el estado de la vivienda**, y la primera asignación de una
> tarea `CREATED` dispara `CLEANER_ASSIGNED`, que la matriz solo admite desde `AWAITING_CLEANING`
> (`properties/domain/state_machine.py`, única fila de ese trigger). Sobre una vivienda en cualquier
> otro estado el `PATCH` responde `409` y la UI lo pinta como «Esa tarea ya no admite un cambio de
> asignación» — un mensaje que habla de la tarea cuando quien bloquea es la vivienda. Medido en
> `dev` el 2026-08-22. Para una tarea que **sí** se pueda asignar, §5.

---

## 5. Conseguir una limpieza *asignable* (probar la vista de gestión)

Para ejercitar el control de asignación de `/cleaning` no sirve una tarea creada a mano (§4): hace
falta una nacida de un checkout, sobre una vivienda en `AWAITING_CLEANING`. Recorrido verificado en
`dev` el **2026-08-22**, con los cuatro tropiezos que tiene.

**Primero, una segunda limpiadora.** Con una sola activa la auto-asignación del checkout se queda la
tarea (`resolve_auto_assignee` exige exactamente una activa) y el control nunca se habilita, porque
pide elegir a alguien **distinto** del ya asignado. Se crea con el **owner** — `MANAGE_USERS` no lo
tiene el manager, que solo lee usuarios:

```bash
jq -nc '{name:"Cleaner Dos", email:"josegascon+cleaner2@gmail.com", role:"CLEANER"}' \
  | curl -sS -X POST "$BASE/users" -H "Authorization: Bearer $OWNER" \
      -H 'Content-Type: application/json' -d @-
```

Nace con contraseña temporal y `must_change_password`, y **no hace falta cambiarla**: para ser
asignable basta con ser `CLEANER` y estar `ACTIVE`.

**Después, una estancia que termine.** Aquí están los cuatro tropiezos:

1. **No existe la reserva de un solo día.** `check_out_date` tiene que ser estrictamente posterior a
   `check_in_date` (`reservations/domain/entities.py`), y a la vez el trigger `CHECKIN_WINDOW_OPENED`
   exige que el check-in sea **hoy** (`state_machine.py`). Así que se crea hoy→mañana y luego se
   mueven las fechas un día atrás con un `PATCH`, cuando la vivienda ya está ocupada y el trigger de
   check-in ya no hace falta.
2. **Las horas se interpretan en la zona de la vivienda** (`Europe/Madrid`), no en UTC. La VM está en
   UTC: calcúlalas con `TZ=Europe/Madrid date`, o en verano te salen dos horas en el pasado y la
   cadena no arranca.
3. **La reserva nace `PENDING`.** El `POST` no acepta `status`; hay que confirmarla con un `PATCH`.
   Sin `CONFIRMED` ningún trigger de reloj la mira.
4. **`channel` debe ser `DIRECT` o `MANUAL`**: un canal de OTA se rechaza porque esa vía es la del
   PMS y su clave de idempotencia.

**Y los tres jobs, a mano.** No hay que esperar a `beat`: son tareas Celery cuya lógica corre
síncrona, así que se invocan directamente y además devuelven su informe, que es lo que dice si la
transición se rechazó y por qué.

```bash
docker compose -f docker-compose.deploy.yml exec -T backend python - <<'JOBS'
from app.scheduler.tasks import check_checkin_windows, mark_occupied_estimated, process_checkouts
print(check_checkin_windows())
print(mark_occupied_estimated())
print(process_checkouts())
JOBS
```

La secuencia de la vivienda es `VACANT_READY` → `AWAITING_CHECKIN` → `OCCUPIED_ESTIMATED` →
`AWAITING_CLEANING`, y en ese último salto `process_checkouts` crea la tarea en la misma
transacción: `transitioned: 1` con `transitioned_without_task: 0` es la prueba de las dos mitades.
Con dos limpiadoras activas la tarea queda **`CREATED` sin asignar** — y entonces sí, el botón de
`/cleaning` se habilita y la asignación pasa.

Un `not_eligible: 1` en `process_checkouts` no es un fallo del job: es que la hora de salida aún no
ha pasado. Mueve `check_out_time` al pasado y vuelve a lanzarlo.
