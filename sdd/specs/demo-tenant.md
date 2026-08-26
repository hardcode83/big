# Tenant de demostración

## Purpose

Un **segundo tenant**, «AutoHostAI Demo», que convive con el de trabajo del equipo en el mismo
entorno `dev` público (https://autohostai.digitalsec.work) y existe para que gente de fuera pueda
recorrer el producto sin recibir las llaves del entorno del equipo. Tiene cuatro cuentas con una
contraseña **conocida, publicable y convergente**, un comando que lo aprovisiona y lo resetea por el
mismo camino, y un workflow con `schedule:` que lo devuelve a su estado inicial cada noche sobre el
runner self-hosted que ya corre en la VM.

El límite de seguridad **es el aislamiento por tenant**, y no un entorno aparte: la demo comparte VM,
base de datos y bucket con `AutoHostAI Dev`. Lo que hace aceptable publicar una credencial es que esa
credencial no alcanza nada fuera de su tenant, y que `saas-cross-tenant` sigue cerrada.

## Requirements

### Identidad del tenant: constantes del módulo, no configuración

- THE SYSTEM SHALL identificar el tenant de demostración por el nombre constante `AutoHostAI Demo`
  (`DEMO_TENANT_NAME`), y THE SYSTEM SHALL NOT ofrecer argumento, bandera ni variable de entorno que
  nombre otro tenant. La seguridad es **por construcción**: no hay parámetro que apuntar a otro sitio.
- THE SYSTEM SHALL declarar como constantes las cuatro direcciones y su rol —
  `owner@demo.autohostai.test` (`TENANT_OWNER`), `manager@demo.autohostai.test`
  (`PROPERTY_MANAGER`), `cleaner@demo.autohostai.test` (`CLEANER`),
  `technician@demo.autohostai.test` (`TECHNICIAN`)—, más `billing@demo.autohostai.test` como
  `tenants.billing_email`, que es columna del tenant y no un login, y por eso no toma prestada la
  dirección del owner.
- El dominio es `.test` (RFC 2606) a propósito: no resuelve, así que el día que llegue SMTP con
  `hardening-release` ningún correo de la demo saldrá a ninguna parte.
- THE SYSTEM SHALL resolver el tenant por igualdad **exacta** de `tenants.name`, no
  case-insensitive, porque así lo resuelven `bootstrap` y `seed_demo`: un nombre con otra caja es
  otra fila, y refusar sobre ella refusaría una ejecución que nunca estuvo en peligro.

### Un solo comando que aprovisiona y resetea por el mismo camino

- THE SYSTEM SHALL exponer un único comando, `python -m app.cli.demo_reset` (`make demo-reset`), sin
  argumentos ni banderas, que ejecuta **la misma secuencia de fases** exista o no el tenant: en la
  primera ejecución lo crea, en las siguientes lo vacía y lo vuelve a sembrar.
- THE SYSTEM SHALL componer `bootstrap.apply_plan` y `seed_demo.apply_plan` construyendo él mismo sus
  planes, y THE SYSTEM SHALL NOT llamar al `build_plan()` de ninguno de los dos: aquellos leen la
  configuración del entorno, y este comando no toma de ahí ni el tenant ni las cuentas.
- WHEN el reset termina con éxito, THE SYSTEM SHALL dejar el tenant en un estado indistinguible del
  que produce un aprovisionamiento desde cero **ese mismo día**. La excepción declarada es
  `users.last_login_at`, que no converge, y el `audit_logs` acumulado, que se preserva.

### Los tres rechazos, cada uno antes de escribir nada

- IF `BOOTSTRAP_TENANT_NAME` nombra exactamente `AutoHostAI Demo`, THEN THE SYSTEM SHALL rechazar la
  ejecución con código 1 **sin abrir transacción**, diciendo que nada se ha escrito. En el entorno
  desplegado esta guarda casi nunca dispara —el `.env` del deploy no lleva `BOOTSTRAP_*`, así que el
  valor está vacío—, y consta como tal: la guarda real es la constante.
- IF existe una fila llamada `AutoHostAI Demo` cuyo `billing_email` **no** es
  `billing@demo.autohostai.test`, THEN THE SYSTEM SHALL rechazarla con código 1 sin escribir nada. Es
  el guardián de identidad: impide adoptar como demo un tenant ajeno que sólo comparte el nombre, y
  corre dentro de la transacción pero fuera de toda fase, para que salga como rechazo (1) y no como
  fallo de fase (2).
- IF `DEMO_ACCOUNT_PASSWORD` falta o no satisface la política de contraseñas, THEN THE SYSTEM SHALL
  rechazar la ejecución con código 1 antes de abrir sesión, nombrando la variable y **sin echar el
  valor**.
- THE SYSTEM SHALL exigir además que toda escritura y todo borrado con scope corran sobre una sesión
  **marcada al tenant de demostración**, comprobándolo (`require_session_bound_to`) en vez de
  confiarlo, y fallando con error propio si la sesión no está marcada o está marcada a otro tenant.

### La contraseña: fuera del árbol, validada antes, convergente y acotada

- THE SYSTEM SHALL tomar la única contraseña de las cuatro cuentas de `DEMO_ACCOUNT_PASSWORD`, y el
  árbol de código SHALL NOT contener ningún valor por defecto para ella: `.env.example` la declara
  por nombre y vacía.
- THE SYSTEM SHALL validarla contra la política del dominio (`assert_password_acceptable`:
  `PASSWORD_MIN_LENGTH` = 12, `PASSWORD_MAX_BYTES` = 72) **antes de abrir transacción**. El umbral
  no es cosmético: por debajo, el propio sistema rechazaría que un visitante volviera a fijarla desde
  `POST /auth/change-password`.
- La validación vive en el comando y **no** en `Settings`: una contraseña corta tiene que tumbar el
  comando, no impedir que arranque la aplicación entera.
- WHEN el reset corre y alguna de las cuatro cuentas tiene otra contraseña, THE SYSTEM SHALL
  restaurarla al valor configurado — es **convergente**, no *create-only* —, y SHALL revocar todas
  las sesiones de esa cuenta, de modo que lo que un visitante dejara abierto muere con el reset.
- THE SYSTEM SHALL converger también el nombre visible y el rol de cada una de las cuatro cuentas, y
  SHALL auditar el rol bajo su propia acción cuando cambie.
- THE SYSTEM SHALL NOT aplicar esa contraseña a ninguna cuenta fuera del tenant de demostración, y
  SHALL comprobarlo en vez de confiarlo: la sesión marcada, la cláusula de tenant explícita en la
  lectura de cada usuario, y el índice único global de correo, que hace que «es de la demo» y «es del
  vecino» sean mutuamente excluyentes para una misma dirección.
- WHERE una de las cuatro direcciones pertenece a **otro** tenant, THE SYSTEM SHALL dejarla intacta y
  no contarla como convergida.
- WHERE alguna de las cuatro cuentas no existe, THE SYSTEM SHALL **informar de la que no encontró**
  en vez de dar por hecho que están las cuatro. Que `users` sea tabla preservada no garantiza que
  estén: la afirmación contraria estuvo escrita y era falsa.
- THE SYSTEM SHALL escribir la fila de auditoría de cada convergencia con el campo `password`
  **redactado**.

### Las fases, la transacción y los códigos de salida

- THE SYSTEM SHALL declarar once fases nombradas y en orden: `configuration`, `refusal`, `prepare`,
  `bootstrap`, `scope`, `delete`, `converge`, `seed`, `storage-sweep`, `purge-audit`, `clear-lock`.
- THE SYSTEM SHALL ejecutar `prepare` … `seed` dentro de **una sola transacción**, de modo que un
  fallo en cualquiera de ellas revierta también el borrado: la base queda sin cambios parciales.
- THE SYSTEM SHALL ejecutar `storage-sweep` y `clear-lock` **después** del commit y fuera de la
  transacción, y THE SYSTEM SHALL NOT permitir que un fallo en ellas tumbe la ejecución: se recogen
  como notas.
- IF alguna fase de la transacción falla, THEN THE SYSTEM SHALL salir con código **2** nombrando la
  fase y **únicamente la clase** de la excepción, nunca su detalle — un error de SQLAlchemy se
  serializa con su sentencia y sus parámetros, y uno de esos parámetros es el hash bcrypt de una
  cuenta viva.
- THE SYSTEM SHALL usar código **1** para «nada escrito» (configuración o rechazo), **2** para un
  fallo dentro o fuera de fase, y **0** para el éxito.

### Qué borra y qué preserva

- THE SYSTEM SHALL acotar todo borrado al tenant de demostración, derivando el orden de las tablas de
  la metadata del esquema, de modo que una tabla nueva con una clave ajena exija una decisión
  explícita y un ciclo caiga en CI y no en la VM.
- THE SYSTEM SHALL preservar cuatro tablas: `tenants`, `tenant_configs`, `users` y `audit_logs`. El
  registro de auditoría se mantiene intacto por requisito (y `users` con él, porque
  `audit_logs.actor_user_id` es `ON DELETE SET NULL`: borrar una y conservar la otra rompería el
  registro por cualquiera de los dos lados), **pero** esa preservación lleva una **retención de
  `DEMO_AUDIT_RETENTION_DAYS` = 7 días** que aplica el comando tras el commit — ver «Retención del
  `audit_logs`» más abajo. La constante vive en `backend/app/cli/demo_reset.py` y no en `Settings`,
  no en variable de entorno y no en base de datos, igual que `DEMO_TENANT_NAME` y la política de
  contraseñas: es una decisión de ingeniería, no de despliegue.
- THE SYSTEM SHALL converger `tenants.timezone` a `Europe/Madrid` y `tenants.country` a `ES`,
  informando del valor anterior cuando lo restaura. `timezone` decide el día al que se ancla el
  dataset entero, así que dejarla a merced de un visitante sería dejarle mover las fechas de la demo.
- THE SYSTEM SHALL anclar las fechas del dataset al día del **calendario del tenant**, no al de UTC.

### Retención del `audit_logs`

- THE SYSTEM SHALL declarar `DEMO_AUDIT_RETENTION_DAYS = 7` como constante del módulo
  `backend/app/cli/demo_reset.py`, alineada con las demás constantes del comando, y THE SYSTEM SHALL
  NOT exponer esa ventana como variable de entorno, campo de `Settings` ni columna de base de
  datos.
- WHEN la fase `purge-audit` del comando corre, THE SYSTEM SHALL borrar las filas de `audit_logs`
  cuyo `tenant_id` es el del tenant de demostración y cuyo `created_at` es **estrictamente anterior**
  al corte `started_at - DEMO_AUDIT_RETENTION_DAYS`, donde `started_at` es el reloj capturado por la
  fase `prepare` de la misma ejecución (`started_at - INTERVAL '7 days'`).
- THE SYSTEM SHALL ejecutar ese `DELETE` **únicamente** sobre el tenant de demostración, sobre una
  sesión ya marcada al tenant (`require_session_bound_to`), y THE SYSTEM SHALL NOT abrir una segunda
  sesión ni saltarse el marcador. WHERE el `tenant_id` resuelto no es el del demo, THE SYSTEM SHALL
  rechazar la fase con código 2 sin escribir nada — la guarda es la constante del módulo, y la del
  `WHERE tenant_id = :tenant_id` literal es redundancia explícita sobre el listener.
- THE SYSTEM SHALL añadir la fase `purge-audit` a la enumeración `PHASES` en la posición **entre**
  `storage-sweep` y `clear-lock`, y SHALL ejecutarla **fuera** de la transacción del reset, igual
  que `storage-sweep` y `clear-lock`: un fallo del `DELETE` no puede revertir el reset ya
  comprometido.
- IF la fase `purge-audit` falla, THEN THE SYSTEM SHALL recoger el fallo como una nota con la forma
  `purge-audit: failed with <ClassName> (detail withheld on purpose)`, y SHALL NOT emitir la
  contraseña, su hash, ningún token de sesión ni el detalle de un `SQLAlchemyError` — el mismo
  contrato que `clear_login_locks` y `storage-sweep`. El fallo degradado es exit 0, no 2.
- THE SYSTEM SHALL escribir **antes** del `DELETE` una fila de auditoría de la propia fase
  `purge-audit`, con `action='AUDIT_LOG_PURGED'`, `entity_type='AUDIT_LOG'`,
  `entity_id=uuid.uuid5(tenant_id, "demo-audit-purge")`, `actor_user_id=NULL`, y `changes` con
  `deleted_count` (entero, escrito con `0` porque el conteo se conoce sólo tras el `DELETE`) y
  `cutoff` (la `cutoff.isoformat()` usada). La fila pasa por `AuditLogFactory.build` + `ChangeSet`
  para que la regla 11 de `steering/security.md` siga cumpliéndose por construcción.
- THE SYSTEM SHALL auditar la fila dentro de la propia fase exactamente una vez — si la escritura
  inicial falla, la nota degradada se reporta sin reentrar en `audit.add`.
- WHEN el reset termina con éxito, THE SYSTEM SHALL emitir en su informe el número de filas de
  `audit_logs` purgadas bajo `audit_logs_purged=N` y el `cutoff` usado, junto al resto de los
  recuentos.

### El barrido de objetos del almacén

- THE SYSTEM SHALL recoger, **antes** del borrado, todas las claves de almacenamiento del tenant,
  descubriendo dinámicamente las columnas `*storage_key` del esquema para que una columna nueva no se
  quede fuera en silencio.
- THE SYSTEM SHALL comprobar que cada clave vive bajo el prefijo `tenants/<tenant_id>/` y THE SYSTEM
  SHALL NOT borrar ninguna que no lo cumpla, reportándolas como **rechazadas**: una clave ajena en esa
  lista es evidencia de que una lectura con scope trajo filas de otro tenant.
- THE SYSTEM SHALL borrar las suyas e informar de cuántas borró, de las que no pudo, y de si no había
  almacén utilizable. El requisito original pedía sólo **enumerar** los huérfanos; borrarlos se añadió
  encima, por operación, y por eso el ciclo de vida de la base y el del almacén dejan de divergir en
  cada reset.

### La salida: recuentos, y un único secreto que sí se emite

- THE SYSTEM SHALL NOT emitir la contraseña, su hash ni ningún token de sesión por la salida del
  comando, sus logs o el informe del workflow. El plan y el informe redefinen su `__repr__` para que
  no los echen, y las contraseñas de los planes que compone van marcadas `repr=False`: el `__repr__`
  generado imprimía la contraseña cinco veces, y el del informe llegó a colar el token del portal en
  el marco de un traceback de pytest.
- THE SYSTEM SHALL emitir **una sola excepción, nombrada y acotada**: el enlace del portal de huésped
  de la estancia activa, precedido del prefijo constante `guest portal for the active stay`. Ese
  prefijo es un **contrato con el workflow**, que lo grepea para publicar el enlace en el resumen del
  job; editarlo dejaría de publicar el enlace sin que nada se pusiera rojo, y un test pina los dos.
- La excepción está acotada por tres hechos y no por una intención: es el token del tenant de
  demostración, así que lo que abre son datos de demostración; muere en el reset siguiente, que revoca
  el token vivo y borra la estancia entera; y no hay otro canal por el que pueda llegar a nadie. **No
  alcanza a la contraseña ni a su hash**, ni a ningún otro token del sistema.

### El dataset llega a las pantallas que existen

- THE SYSTEM SHALL sembrar al menos una conversación cuyos mensajes de huésped entran **por la vía
  real de entrada** (`ProcessInboundGuestMessageUseCase`), no por inserción directa, de modo que la
  clasificación, la política de escalado y la respuesta automática queden ejercitadas y visibles en el
  hilo. Escribir las filas habría producido un hilo que parece correcto y no ejercita nada.
- THE SYSTEM SHALL usar el adaptador determinista `MockAIAdapter` —el mismo que inyecta el router
  real—, de modo que la siembra **no dependa de red ni de credenciales** de ningún proveedor de IA.
- THE SYSTEM SHALL elegir los dos textos para caer en intenciones fijadas por test (`WIFI` y
  `EMERGENCY`), que son las que ejercitan las dos ramas: la respuesta con plantilla y el escalado a
  una persona.
- THE SYSTEM SHALL emitir un enlace de portal de huésped válido para la estancia activa. Sólo se
  persiste su digest; el valor en claro existe una vez y se publica junto con las credenciales.
- WHERE el llamante no pide el enlace —lo que hace `make seed-demo` sobre el tenant de trabajo—, THE
  SYSTEM SHALL no mintar ningún token.

### El disparo periódico, sin exponer la base ni la API

- THE SYSTEM SHALL ejecutar el reset desde el workflow `.github/workflows/demo-reset.yml`, con
  `schedule: "15 3 * * *"` (03:15 UTC diario) y `workflow_dispatch` para el disparo manual, acotado a
  `main`. El desplazamiento respecto de la hora en punto es deliberado: GitHub encola con imprecisión
  los cron en `:00`, y a las 06:00 UTC corre el beat de recomendaciones de precio.
- THE SYSTEM SHALL correrlo en el **runner self-hosted que ya existe** (`runs-on: [self-hosted, dev]`,
  el mismo grupo que el job de deploy), con `permissions: contents: read`, `timeout-minutes: 20` y
  `concurrency` **compartida con el deploy** (`group: deploy-dev`, sin cancelación), para que un reset
  no pueda cruzarse con un redespliegue que reescribe el `.env` y recrea contenedores.
- THE SYSTEM SHALL alcanzar la base de datos con un contenedor **de un solo uso** sobre el stack vivo
  (`run --rm --no-deps -T backend`), que entra por la red interna del compose; y THE SYSTEM SHALL NOT
  abrir ningún puerto entrante, publicar la base de datos, requerir SSH ni modificar el security list.
- THE SYSTEM SHALL hacer `checkout` con `clean: false`, porque el `.env` del despliegue no está
  versionado y vive en el workspace compartido del runner; y SHALL fallar en rojo, antes de tocar
  nada, si ese `.env` no está o si `postgres` no está corriendo.
- THE SYSTEM SHALL leer la contraseña del **OCI Vault por nombre**
  (`autohostai-<env>-demo-account-password`) con el **instance principal** de la VM, enmascararla
  (`::add-mask::`) en cuanto la tiene, y pasarla al contenedor **sin valor en la línea de órdenes**
  (`-e DEMO_ACCOUNT_PASSWORD`), para que no aparezca en la tabla de procesos. No es un secret de
  Actions ni vive en el repositorio; lo único que el workflow lee de GitHub es la *variable*
  `OCI_VAULT_ID`.
- WHEN el reset falla, THE SYSTEM SHALL terminar el workflow en rojo nombrando la fase, sin volcar la
  contraseña ni el detalle de una excepción de base de datos.
- THE SYSTEM SHALL publicar el enlace del portal en el resumen del job y THE SYSTEM SHALL borrar
  siempre (`if: always()`) el fichero intermedio que lo transporta: es un token vivo en el workspace
  persistente de un runner self-hosted.

### Todo lo anterior, declarado como código

- THE SYSTEM SHALL declarar en Terraform el secreto del Vault (`oci_vault_secret`, nombre derivado de
  `var.env`) sembrado con un `random_password` inerte de 24 caracteres sin símbolos, con
  `lifecycle { ignore_changes = [secret_content] }` para que el valor real, puesto **out-of-band**,
  sobreviva a los `apply` siguientes.
- THE SYSTEM SHALL autorizar su lectura añadiendo el OCID del secreto a la enumeración
  `target.secret.id` de la policy que ya tiene el dynamic-group del runner — una cláusula más en la
  sentencia existente, no una policy nueva ni un dynamic-group nuevo.
- **Comprobación pendiente, declarada y no resuelta por este change**: que el provider de OCI honre de
  verdad `ignore_changes = [secret_content]`. Si no lo hiciera, un `terraform apply` devolvería la
  contraseña al valor generado y el reset siguiente la propagaría a las cuatro cuentas, dejando las
  credenciales publicadas sin funcionar **en silencio**. La señal es un `plan` que proponga reescribir
  `secret_content` teniendo ya el valor out-of-band puesto; la salida, si no aguanta, es publicar la
  contraseña que genera `random_password` y rotarla con `apply -replace`.

### Documentación de operación

- THE SYSTEM SHALL documentar en `docs/demo-tenant.md` las cuatro cuentas con su rol y qué puede hacer
  cada una, y SHALL declarar explícitamente **qué secciones de la aplicación no son demostrables
  todavía** — hoy la bandeja de conversaciones, la pantalla de precios y las apps de limpiadora y
  técnico, que son `RoutePlaceholder`, más el hecho de que `AuthGuard` no distingue rol.
- THE SYSTEM SHALL documentar cómo se cambia la contraseña y **qué hay que ejecutar para que surta
  efecto**: rotar el valor del Vault no hace nada hasta que corre un reset.
- THE SYSTEM SHALL documentar el reset manual (`gh workflow run demo-reset.yml --ref main`, o
  `make demo-reset` en local) y su cadencia programada, con sus tres salvedades: `schedule:` se
  desactiva tras 60 días sin actividad en el repo, la hora no es exacta, y con el runner caído el job
  espera en cola.

## Límites aceptados

Los tres son decisiones tomadas con su motivo escrito, no descuidos:

- **Un visitante puede desactivar el reset para siempre.** La contraseña del `TENANT_OWNER` se publica
  a propósito y ese rol tiene `MANAGE_TENANT_SETTINGS`, así que puede cambiar `billing_email` por
  `PATCH /tenants/{id}` — y entonces el guardián de identidad refusa en todas las ejecuciones
  siguientes: el tenant **deja de resetearse** y lo que los visitantes metieran, PII de huésped
  incluida, sobrevive al borrado nocturno. Nótese la dirección del fallo: **cierra, no abre**; lo que
  se acepta es que un visitante pueda provocar ese cierre. La mitigación es operativa y no de código:
  devolver `billing_email` a `billing@demo.autohostai.test` a mano, documentado en
  `docs/demo-tenant.md`. La alternativa fuerte —identificar el tenant por su clave primaria y
  converger `name`/`billing_email`— se descartó por lo que costaba.
- **Cuatro cuentas con contraseña publicada son cuatro cuentas que cualquiera puede usar para agotar
  recursos del tenant** (subir fotos, abrir incidencias). No se añade ninguna cuota; la contención es
  el aislamiento por tenant y el reset diario, que hace que lo acumulado viva menos de 24 h.
- **Las cuatro direcciones son constantes públicas, así que cualquiera puede mantenerlas bloqueadas**
  repitiendo intentos fallidos cada ventana de bloqueo. El bloqueo nunca fue permanente —expira por
  TTL—, y lo que este comando hace es **limpiarlo antes de tiempo** al terminar; no mitiga el bloqueo
  sostenido.

## Key files

- Comando: `backend/app/cli/demo_reset.py` — constantes del tenant y de las cuatro cuentas, `PHASES`,
  `build_plan`, `refuse_if_the_working_tenant_is_the_demo_tenant`,
  `refuse_a_tenant_that_only_shares_the_name`, `delete_the_tenants_rows`,
  `converge_the_demo_passwords`, `collect_storage_keys`, `sweep_storage`, `clear_login_locks`,
  `purge_old_audit_logs`, `_safe_purge_old_audit_logs`, `main`.
- Vías que compone: `bootstrap.apply_plan` y `seed_demo.apply_plan`
  (`backend/app/cli/{bootstrap,seed_demo}.py`); la conversación y el enlace de portal viven en
  `seed_demo.py` (ver [`seed-data-demo.md`](seed-data-demo.md)).
- Guardas de sesión: `require_session_bound_to` (`backend/app/core/db.py`),
  `TenantUnmarkedSessionError` / `TenantMismatchedSessionError` (`backend/app/core/tenancy.py`).
- Política de contraseña: `backend/app/auth/domain/password_policy.py`.
- Configuración: `backend/app/core/config.py` (`demo_account_password`), `.env.example`.
- Orquestación: `Makefile`, target `demo-reset`; `.github/workflows/demo-reset.yml`.
- Infra: `infra/environments/dev/main.tf` (`random_password.demo_account`,
  `oci_vault_secret.demo_account_password`, la enumeración de
  `oci_identity_policy.dev_runner_read_secrets`), `iam-policy.md`, `RUNBOOK.md` §10.
- Tests: `backend/tests/cli/test_demo_reset.py` (rechazos, convergencia, aislamiento del vecino,
  fases y códigos, barrido, anclaje de fechas, y el workflow leído como contrato ejecutable),
  `backend/tests/cli/test_seed_demo.py` (conversación y enlace de portal).
- Documentación: `docs/demo-tenant.md`, enlazada desde `docs/README.md`; `README.md` §demo.
