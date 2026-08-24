# Tasks: demo-user

Deriva de `proposal.md` (R1-R6) y `design.md` (D1-D20). Las secciones están ordenadas para
que el árbol quede en verde después de cada una: la 1 y la 2 no escriben nada en base de
datos, la 3-5 construyen el comando por fases, y la 6 en adelante sólo añaden superficie
(seed, Makefile, Terraform, workflow, docs).

Nada está pre-implementado: `backend/app/cli/demo_reset.py`, `.github/workflows/demo-reset.yml`,
`docs/demo-tenant.md` y el test del comando no existen, y ni `demo_account_password` ni
`DEMO_ACCOUNT_PASSWORD` aparecen en `backend/app/core/config.py`, `.env.example` o `Makefile`
(comprobado el 2026-08-23). Así que no hay ninguna tarea pre-marcada.

## 1. Configuración: una sola variable, sin default en el árbol <!-- panel: N/A (config) 2026-08-23 -->

- [x] 1.1 Añadir `demo_account_password: str = ""` al bloque de credenciales de aplicación de
      `backend/app/core/config.py`, junto a los ocho `bootstrap_*`/`seed_*` que ya son
      `str = ""` — sin `field_validator`, porque la validación vive en `build_plan` (D3).
      Test en `backend/tests/cli/test_demo_reset.py`: `Settings().demo_account_password == ""`,
      es decir el ajuste **no trae contraseña por defecto**. [R2.1]
- [x] 1.2 Añadir a `.env.example` la línea `DEMO_ACCOUNT_PASSWORD=` —nombre sin valor— con su
      comentario: para qué es, que es obligatoria para `make demo-reset`, que debe tener
      ≥ `PASSWORD_MIN_LENGTH` (12) caracteres y que en el entorno remoto la sirve el Vault.
      Test que **lee el fichero** y falla si esa línea tiene algo a la derecha del `=`
      (D18.2). [R2.1]

## 2. El comando: constantes, plan validado y refusal — todo antes de abrir transacción <!-- panel: PASS 2026-08-23 -->

- [x] 2.1 Crear `backend/app/cli/demo_reset.py` con las constantes de D2:
      `DEMO_TENANT_NAME = "AutoHostAI Demo"` y las cuatro direcciones
      `owner|manager|cleaner|technician@demo.autohostai.test`, más los nombres de las cuatro
      cuentas. **No existe ningún parámetro, argumento ni variable de entorno por el que este
      módulo pueda nombrar otro tenant.** Test que fija las cinco constantes por valor. [R1.2]
- [x] 2.2 `build_plan()` en el mismo módulo: valida `DEMO_ACCOUNT_PASSWORD` contra
      `PASSWORD_MIN_LENGTH` importado de `backend/app/auth/domain/password_policy.py`, y
      **construye** `bootstrap.BootstrapPlan` y `seed_demo.SeedPlan` directamente desde las
      constantes de 2.1 —no llama a los `build_plan()` de esos módulos, que leen
      `BOOTSTRAP_*`/`SEED_*` del entorno y nombrarían el tenant de trabajo—. Tests: ausente →
      código 1 nombrando la variable sin ecoar valor; 11 caracteres → código 1 sin escribir
      nada (D18, cierre de R2.3); 12 caracteres → plan construido con las cuatro cuentas y sus
      roles (`TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`). [R2.1, R2.3, R1.2]
- [x] 2.3 Refusal explícita: si `settings.bootstrap_tenant_name` está puesto y es igual a
      `DEMO_TENANT_NAME`, salir con código 1 sin abrir transacción. Test que además afirma que
      la base queda **byte a byte** igual (D18, último párrafo). [R1.4, R3.2]
- [x] 2.4 `main()` con las fases nombradas de D15 (`configuration`, `refusal`, `bootstrap`,
      `delete`, `converge`, `seed`, `storage-sweep`, `clear-lock`) y sus códigos: `0` correcto;
      `1` configuración, refusal o precondición (nada escrito); `2` fallo inesperado
      imprimiendo **sólo la clase** de la excepción y nunca su detalle —los errores de
      SQLAlchemy anexan la sentencia con sus parámetros, y entre ellos va un hash de bcrypt—.
      La salida normal son recuentos por entidad y las fases recorridas. Tests: el mensaje de
      un fallo simulado en cada fase nombra la fase y **no** contiene la contraseña, su hash ni
      el detalle de la excepción. [R3.4, R2.5, R5.5]

## 3. Fase de borrado, acotada al tenant por el mecanismo que ya existe <!-- panel: PASS 2026-08-23 -->

- [x] 3.1 Fase `delete` en `demo_reset.py`: `sqlalchemy.delete(Modelo)` por el ORM sobre la
      sesión ya marcada con `bind_session_to_tenant(session, demo_tenant.id)`, recorriendo las
      tablas en el orden de `Base.metadata.sorted_tables` **invertido** (topológico al revés,
      por las 51 claves ajenas `RESTRICT`), excluyendo las cuatro de D5: `tenants`,
      `tenant_configs`, `users`, `audit_logs`. Ficheros: `backend/app/cli/demo_reset.py`,
      leyendo `tenant_scoped_classes()` de `backend/app/core/db.py:49`. [R1.5, R3.2, R3.6]
- [x] 3.2 Test de cobertura de tablas: el conjunto que la fase recorre es **exactamente**
      `tenant_scoped_classes()` menos la lista de exclusión de D5, de modo que una tabla nueva
      sin decisión explícita ponga el test en rojo en CI en vez de quedarse sin borrar en
      silencio sobre el entorno público. [R1.5]
- [x] 3.3 Borrar las cuatro tablas hijas sin `tenant_id` por su padre con scope (D6):
      `messages` por `conversations`, `cleaning_checklist_completions` y `cleaning_photos` por
      `cleaning_tasks`, `review_response_drafts` por `reviews` — patrón
      `DELETE ... WHERE <fk> IN (SELECT id FROM <padre> WHERE tenant_id = :demo)`. Test de que
      las filas del vecino en esas cuatro tablas sobreviven. [R1.5]
- [x] 3.4 Test de aislamiento de D18.3: dos tenants en la base, fotografía de **todas** las
      filas del tenant de trabajo antes y después de la fase, y afirmación de igualdad. La
      lectura de verificación va sobre una sesión **no marcada** o marcada al vecino — sobre una
      marcada al tenant de demostración el test no puede fallar, porque el listener filtra hasta
      el `select` de una columna. Comprobar que cae al sustituir el DELETE del ORM por uno en
      Core sin cláusula de tenant. [R1.5, R3.2]
- [x] 3.5 Test de que `user_sessions` y `password_reset_tokens` del tenant de demostración **sí**
      se borran (D5, último párrafo) y de que las filas de `webhook_events` con `tenant_id`
      `NULL` quedan fuera del borrado sin necesidad de excluirlas. [R1.5, R3.1]

## 4. Convergencia de la contraseña, acotada a las cuatro cuentas <!-- panel: PASS 2026-08-23 -->

- [x] 4.1 Fase `converge` en `demo_reset.py`, copiando paso por paso el precedente de
      `backend/app/cli/reset_password.py` (D9), para cada una de las cuatro direcciones
      constantes y **comprobando el `tenant_id` de la fila contra el id del tenant de
      demostración antes de escribir**: `set_password_hash(..., temporary=False)`,
      `users.apply_changes(...)`, fila de `AuditLog` con `action=actions.USER_PASSWORD_RESET`,
      `changes=ChangeSet(actions.ENTITY_USER).redacted("password")` y **sin actor**, y
      `revoke_all_for_user(..., SessionRevokedReason.PASSWORD_RESET)`. Tests: la contraseña
      queda verificable con el valor configurado aunque la cuenta tuviera otra (convergencia, no
      create-only); `must_change_password` es `False` (R1.3); las sesiones vivas del visitante
      anterior quedan revocadas. [R1.3, R2.2, R2.4]
- [x] 4.2 `clear_lock(user_id)` sobre `RedisLoginThrottle`
      (`backend/app/auth/infrastructure/throttle.py`) **fuera de la transacción y después del
      commit** (D9.5): Redis y Postgres no comparten transacción, así que un fallo del cerrojo
      no puede tumbar un reset ya commiteado. Test de que un fallo de Redis deja el comando en
      código 0 informando de la degradación. [R2.2]
      **Parcialmente hecho, y por eso sigue sin marcar** (panel de QA de la sección 4): la función
      existe, es por cuenta y devuelve los ids que no pudo limpiar, y hay dos tests suyos. Lo que
      faltaba era lo que la tarea dice literalmente —«deja **el comando** en código 0»—, y eso no
      era comprobable hasta que 5.1 conectara las fases a `run()`/`main()`. **Cerrada ahí**, con
      `test_a_redis_failure_leaves_the_command_at_exit_zero`.
- [x] 4.3 Test del vecino de D18.1: un segundo tenant con una cuenta cuya contraseña se conoce;
      tras el comando, esa contraseña **sigue verificando** y su `password_hash` no cambió.
      Lectura sobre sesión no marcada o marcada al vecino, por el mismo motivo que 3.4.
      Comprobar que cae al quitar el `tenant_id` de la comprobación previa de 4.1. [R2.4]

## 5. Composición transaccional, siembra y barrido de objetos <!-- panel: PASS 2026-08-24 (2 rondas; los arreglos de la ronda 2 quedan para /sdd:review) -->

- [x] 5.0 Enmienda de D10bis en `backend/app/cli/seed_demo.py`: `resolve_known_accounts(session,
      plan)` con el bucle de `find_by_email_globally` (exige sesión **sin marcar**), y parámetro
      opcional `known_accounts=None` en `apply_plan` que lo usa si se lo dan y lo resuelve él
      mismo si no — para que `make seed-demo` no cambie de comportamiento. Es lo que permite que
      `demo_reset` resuelva las cuentas antes de marcar la sesión y que el borrado de D4 siga
      yendo por el ORM sobre una sesión marcada dentro de la transacción única de D7. Tests: con
      `known_accounts` dado no se hace ninguna lectura sin scope; sin él, comportamiento
      idéntico al actual; y `apply_plan` completo sobre una sesión **ya marcada** al mismo tenant
      no lanza `TenantMarkedSessionError`. [R3.1, R3.4]
- [x] 5.1 **Toma el cerrojo de `tenants` una sola vez, en la cabeza de la transacción**, y no
      dentro de `converge`: el panel de seguridad de la sección 4 señaló una inversión de orden
      de cerrojos —la fase de borrado toma cerrojos de fila sobre `users` antes de que
      `converge` pida el de `tenants`, mientras `user_admin` pide el de `tenants` primero—, así
      que un `PATCH` concurrente puede interbloquear contra el reset y Postgres abortará a uno de
      los dos. Es de disponibilidad y se cura al día siguiente, pero mover el cerrojo arriba lo
      elimina y no cuesta nada. Composición de D1/D7 en `demo_reset.py`: `bootstrap.apply_plan(session, plan, hasher)`
      en **su propia** transacción (commitea por su cuenta; en un reset es un no-op que no
      escribe nada), y después `delete → converge → seed` compartiendo sesión en **una sola**
      transacción, cuyo único `commit` es el que ya hace `seed_demo.apply_plan(..., now=...)`
      al final de su fase de reloj. Tests: sobre un tenant inexistente lo aprovisiona; sobre uno
      existente lo resetea; y un fallo inyectado en `seed` deja la base **sin cambios
      parciales** —el borrado también revierte— y sale con código distinto de cero nombrando la
      fase. [R1.1, R3.1, R3.4]
- [x] 5.2 Fase `storage-sweep` (D16): recoger las `storage_key` de `cleaning_photos` e
      `incident_photos` del tenant de demostración **antes** del borrado de filas.
      **Ojo, del panel de seguridad de la sección 3**: `cleaning_photos` **no tiene
      `tenant_id`** (quinto límite del listener), así que esa recogida previa tiene que unir
      `cleaning_tasks` explícitamente —`WHERE cleaning_task_id IN (SELECT id FROM cleaning_tasks
      WHERE tenant_id = :demo)`, el patrón de D6— o leería las fotos de **todos** los tenants y
      el barrido borraría del almacén objetos ajenos. `incident_photos` sí lleva `tenant_id` y la
      sesión marcada la cubre. El resto de la tarea sigue igual: y borrarlas
      por `FileStoragePort.delete(key)` a través de `ConfiguredFileStorageFactory`
      **después** de que el commit haya salido bien, informando de cuántas borró y **cuáles no
      pudo**. Un fallo del almacén no pone el comando en rojo. Tests: el orden (nada se borra
      del almacén si la transacción revierte) y el informe de las claves que fallaron. [R3.5]
- [x] 5.3 Test de R3.3 (D17): ejecutar el comando sobre una base vacía y sobre un tenant ya
      sembrado y manoseado el mismo día, y afirmar que **lo que la API devuelve** es igual —
      composición del dataset, estados operacionales, timeline y fechas—. `audit_logs`,
      `users.created_at` y `users.id` quedan fuera de la comparación, y el test lo declara por
      qué: ningún endpoint los lee. [R3.3]

## 6. El dataset que llega a las pantallas: conversaciones y enlace de portal <!-- panel: PASS 2026-08-24 -->

- [x] 6.1 En `backend/app/cli/seed_demo.py`, fase nueva dentro de `_advance_the_clock`: una
      conversación por `CreateConversationUseCase` anclada a la estancia activa, su vivienda y
      su huésped, y **al menos dos** mensajes por `ProcessInboundGuestMessageUseCase` —la vía
      real de entrada— con `MockAIAdapter` (`backend/app/messaging/infrastructure/ai.py`):
      determinista, sin estado, sin I/O y sin credenciales. Uno de intent reconocido y
      respondible desde el catálogo de plantillas, y uno que dispare
      `EscalationReason.EMERGENCY_KEYWORD` vía `contains_emergency_keyword`
      (`backend/app/messaging/domain/escalation.py`), para que el hilo enseñe las dos ramas.
      Los textos son **constantes del módulo**, en el idioma del tenant, como `_CHECKLIST_ITEMS`
      y los títulos de `SEED_INCIDENTS`. Nuevas claves en el dict `created`. [R4.1, R4.2, R4.4]
- [x] 6.2 Tests en `backend/tests/cli/test_seed_demo.py`: cada texto constante pineado contra el
      intent que debe producir —igual que el seed ya pinea categoría y severidad del
      clasificador de incidencias—, para que ninguno caiga en los tres intents para los que
      `MockAIAdapter.generate_response` lanza `KeyError` a propósito; y que el hilo queda con
      una respuesta automática y una escalada. [R4.1, R4.2]
- [x] 6.3 En el mismo módulo, emitir el enlace de portal con `IssueGuestAccessTokenUseCase`
      (`backend/app/guests/application/portal.py`) sobre la reserva `SEED-AIRBNB-1`,
      pasándole un `CallerOwnedUnitOfWork` para que su `commit()` no rompa la transacción única
      de 5.1. Componer la URL `{settings.frontend_base_url}/guest/{token}` e **imprimirla** —
      es la excepción única y nombrada de R2.5 (D19), porque el valor en claro existe una sola
      vez y sólo se persiste su digest. Test de que la URL sale por la salida y de que el
      token verifica contra su digest. [R4.3, R4.4, R2.5]
- [x] 6.4 Añadir a la tabla de la regla 11 de `sdd/steering/security.md` la fila de
      `messages.content` ← el seed, con el contrato «constantes del módulo» (D11). La
      atribución va **en esa tabla y en ningún otro sitio**. Verificar con
      `backend/tests/test_rule11_ownership.py`, que recorre `sdd/`, `docs/`, `backend/app/`,
      `backend/alembic/versions/` y `backend/tests/`. [R4.4]

## 7. Orquestación local <!-- panel: N/A (un target de Makefile) 2026-08-24 -->

- [x] 7.1 Target `demo-reset` en el `Makefile`:
      `$(COMPOSE) exec backend python -m app.cli.demo_reset` —`python -m` y no `uv run`, por el
      mismo motivo que documentan `bootstrap` y `seed-demo`: `uv` sólo existe en la etapa de
      desarrollo de `backend/devops/Dockerfile`—, con el comentario de por qué no forma parte de
      `up` y de qué variable necesita. [R3.1]

## 8. Terraform: el secreto del Vault y el permiso que lo hace legible

- [x] 8.1 En `infra/environments/dev/main.tf`: `random_password.demo_account` (longitud 24) y
      `oci_vault_secret` con `secret_name = "autohostai-${var.env}-demo-account-password"`,
      contenido inicial ese `random_password` y
      `lifecycle { ignore_changes = [secret_content] }` (D12). El valor publicado lo pone una
      persona out-of-band con `oci vault secret update-base64`; **el valor concreto no se
      escribe en ningún fichero del repositorio**. [R5.4, R5.6, R2.1]
- [x] 8.2 Añadir el OCID de ese secreto al **mismo** `statement` de
      `oci_identity_policy.dev_runner_read_secrets` (`infra/environments/dev/main.tf:237`), en
      el mismo apply que lo crea — es la mitigación que `object-storage-provisioning` ya
      declaró para sus cuatro. [R5.4, R5.6]
> **Post-merge, y antes de publicar las credenciales a nadie: verificar que `ignore_changes`
> aguanta.** No es una tarea de la implementación local, y por eso no es una casilla: `infra-dev.yml`
> acota `plan` **y** `apply` a `refs/heads/main` —su comentario explica que el job lleva
> `CLOUDFLARE_API_TOKEN`, con control del DNS y el TLS de toda la zona, y que una rama arbitraria
> ejecutaría su propia definición del workflow con el secret dentro—, así que no se puede planificar
> desde aquí. Y aunque se pudiera: antes del `apply` el secreto no existe, de modo que un `plan`
> mostraría una **creación** y no diría nada sobre si `ignore_changes` aguanta sobre un recurso ya
> creado. La comprobación sólo significa algo con el valor definitivo dentro.
>
> Todo el diseño de la contraseña depende de que el provider de OCI respete
> `lifecycle { ignore_changes = [secret_content] }` sobre
> `oci_vault_secret.demo_account_password`: si no lo respeta, cada `terraform apply` devuelve el
> secreto al valor de `random_password`, el reset siguiente lo propaga a las cuatro cuentas y las
> credenciales publicadas dejan de funcionar **en silencio**, sin que nada se ponga en rojo.
>
> **Procedimiento, secuencia y las dos salidas posibles**: `infra/environments/dev/RUNBOOK.md`
> §10.2, que es su casa. Resumen: poner el valor out-of-band con `oci vault secret update-base64`
> (§10.1, con `printf` y no `echo`), lanzar `infra-dev` con `action=plan` desde `main`, y —si el
> plan propone reescribir `secret_content`— no aplicar, porque entonces la rotación es
> `terraform apply -replace=random_password.demo_account` y hay que corregir §10.1 y la sección
> equivalente de `docs/demo-tenant.md`, que hoy documentan el otro camino. [R2.2, R5.4]

## 9. El workflow programado

- [x] 9.1 Crear `.github/workflows/demo-reset.yml` con un solo job, según D13:
      `on: schedule [{cron: "15 3 * * *"}]` más `workflow_dispatch`;
      `if: github.ref == 'refs/heads/main'`; `runs-on: [self-hosted, dev]`;
      `permissions: {contents: read}`; `timeout-minutes: 20`; y
      `concurrency: {group: deploy-dev, cancel-in-progress: false}` — el **mismo** grupo que el
      job `deploy` de `deploy-dev.yml`, para que un reset no corra a la vez que un despliegue
      que está reescribiendo el `.env`. `actions/checkout` con `clean: false`, porque el `.env`
      renderizado por el deploy no está versionado y el `git clean -ffdx` por defecto lo
      borraría. [R5.1, R5.2, R5.3, R5.6]
- [x] 9.2 Paso de lectura del Vault por nombre determinista
      (`autohostai-${ENV}-demo-account-password`, `--auth instance_principal`, como ya hace
      `deploy-dev.yml`) seguido **inmediatamente** de `::add-mask::` sobre el valor, antes de
      cualquier otro paso. [R5.4, R5.5]
- [x] 9.3 Precondición explícita antes de invocar: si no existe `.env` o el stack no está
      arriba, fallar en rojo nombrando la fase («precondición: el entorno no está desplegado»)
      en vez de morir dentro de un error de interpolación de Compose. [R5.5]
- [x] 9.4 Paso de invocación de D14:
      `docker compose -f docker-compose.deploy.yml run --rm --no-deps -T -e DEMO_ACCOUNT_PASSWORD -e BOOTSTRAP_STORAGE_TYPE=S3 backend python -m app.cli.demo_reset`
      — `run --rm` y no `exec`; `-e DEMO_ACCOUNT_PASSWORD` **sin `=valor`**, para que no quede
      en la tabla de procesos de la VM; `BOOTSTRAP_STORAGE_TYPE=S3` porque el `.env` desplegado
      no la lleva y sin ella el tenant de demostración nacería `LOCAL`. [R5.2, R5.3]
- [x] 9.5 Publicar en el resumen del job la URL del portal que el comando imprime, y **no**
      enmascararla (D19, última nota); el `::add-mask::` cubre la contraseña y sólo la
      contraseña. Verificar que un fallo del reset termina el workflow en rojo nombrando la
      fase, sin volcar la contraseña ni el detalle de una excepción de base de datos. [R4.3,
      R5.5]

## 10. Documentación <!-- panel: PASS 2026-08-24 -->

> **Contexto para quien retome esto en una sesión limpia.** El stack de este worktree tiene que
> estar arriba (`make up` — **siempre por `make`**, nunca `docker compose up` a secas: sin el
> overlay `docker-compose.worktree.yml` choca de puertos con el stack del principal). Los tests se
> corren con `docker compose exec -T backend uv run pytest …` **directamente**: pasarlos por
> `rtk proxy` ha colgado el wrapper ~600 s en esta suite varias veces aunque pytest terminara en
> ~35 s. Y una cifra de la suite completa sólo vale con `ListAgents` vacío: tres veces en este
> change hubo fallos en `tests/cleaning/` y `tests/pricing/` que pasaban en aislamiento, por
> contención de los agentes del panel contra el mismo contenedor.
>
> Lo que 10.1 tiene que documentar y no está en el proposal, porque salió de los paneles:
> - **La contraseña publicada la puede inutilizar un visitante.** El `TENANT_OWNER` de la demo
>   tiene `MANAGE_TENANT_SETTINGS`, así que puede cambiar `billing_email` del tenant y con eso el
>   guardián de identidad del comando refusa para siempre (código 1, «nothing was written») y la
>   demo deja de resetearse. Límite **aceptado por el usuario** en el gate de la sección 2. Hay que
>   documentar el síntoma (workflow en rojo diciendo que no escribió nada, o el dataset envejecido)
>   y el arreglo a mano: devolver `billing_email` a `billing@demo.autohostai.test`.
> - **Renombrar el tenant también lo rompe**, y falla cerrado de otra forma:
>   `bootstrap.apply_plan` levanta `BootstrapConflictError` (no `MultipleResultsFound`, que es lo
>   que decía la tabla de Risks hasta que un panel lo midió) y no commitea nada.
> - **Qué NO es indistinguible tras un reset** (D17/D17bis): `audit_logs` —que además crece sin
>   límite en este tenant— y `users.created_at`/`id`/`last_login_at`.
> - **El bloqueo de login por 10 fallos**: cualquiera puede bloquear las cuatro cuentas publicadas
>   15 minutos con ~40 intentos, indefinidamente. Sólo disponibilidad, aceptado, pero dicho.
> - **La rotación de la contraseña** es la de la tarea 8.3 (`RUNBOOK.md` §10.2), y depende de cómo
>   salga esa verificación: si `ignore_changes` no aguanta, el procedimiento es
>   `terraform apply -replace` y no `oci vault secret update-base64`.


- [x] 10.1 Crear `docs/demo-tenant.md` (R6): las cuatro cuentas, su rol y qué puede hacer cada
      una; **qué secciones de la aplicación no son demostrables todavía** —la bandeja de
      conversaciones, la pantalla de precios, `/cleaner` y `/tech` (placeholders, y `AuthGuard`
      no distingue rol), valoraciones y statements—; cómo se cambia la contraseña en el Vault y
      qué hay que ejecutar para que surta efecto; el procedimiento de reset manual
      (`workflow_dispatch` y `make demo-reset`) y su cadencia programada, con la advertencia de
      que `schedule:` se desactiva tras 60 días sin actividad en el repo y que la hora no es
      exacta. **Nunca el valor de la contraseña.** [R6.1, R6.2, R6.3]
      - Y **el límite aceptado en el gate de la sección 2** (fila nueva de Risks en `design.md`):
        un visitante con las credenciales publicadas puede cambiar `billing_email` o `name` del
        tenant desde `PATCH /tenants/{id}` —el rol `TENANT_OWNER` tiene
        `MANAGE_TENANT_SETTINGS`— y eso hace que el comando refuse para siempre, dejando la demo
        sin resetear. Documentar el síntoma (workflow en rojo con «nothing was written», o el
        dataset envejecido) y el arreglo a mano: devolver `billing_email` a
        `billing@demo.autohostai.test`. [R6.3]
- [x] 10.2 Actualizar `docs/seed-demo.md` (las conversaciones y el enlace de portal en el
      inventario del seed), `docs/README.md` (enlace a `docs/demo-tenant.md`), el `README.md`
      de la raíz (el target `demo-reset` en la sección de comandos) e
      `infra/environments/dev/RUNBOOK.md` (rotación de la contraseña en el Vault con
      `oci vault secret update-base64`). [R6.2, R6.3]

## 11. Verificación <!-- panel: N/A (verificación; no toca código de producción) 2026-08-24 -->

- [x] 11.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest`
      (con el stack parado, `docker compose run --rm backend uv run pytest`). Contar las cifras
      reales, no un «PASS (0) FAIL (0)».
      **8678 passed, 39 skipped en 781,84 s** (2026-08-24, `-p no:randomly -q`, salida a fichero
      para no pasarla por el filtro de rtk, y con `ListAgents` sin agentes en este worktree). Los
      39 saltados son preexistentes de otras áreas: los tres ficheros del change
      (`test_demo_reset.py`, `test_seed_demo.py`, `test_bootstrap.py`) dan **215 passed, 0
      skipped** con `-rs`.
- [x] 11.2 Terraform: `terraform fmt -check -diff` y
      `terraform init -backend=false -input=false && terraform validate` en
      `infra/environments/dev/` — los mismos comandos del job `validate` de `infra-dev.yml`.
      `fmt -check` sale 0 sin diff; `validate` responde «Success! The configuration is valid.»
      (2026-08-24).
- [x] 11.3 Sin contrato que regenerar: el change no añade ni modifica ninguna ruta, así que
      `backend/openapi.json` no se mueve. Confirmarlo en el diff antes de cerrar (si se moviera,
      hay una ruta que no estaba en el diseño).
      Confirmado en el diff (2026-08-24): ni `backend/openapi.json` ni
      `frontend/lib/api/generated/` aparecen, y ningún fichero de `api/` está tocado — así que
      tampoco aplica la segunda mitad del puente de `steering/documentation.md`.
- [x] 11.4 Prueba de extremo a extremo en el stack local: `make up`, `make bootstrap`,
      `make demo-reset` con `DEMO_ACCOUNT_PASSWORD` puesta; entrar con
      `owner@demo.autohostai.test`, comprobar que el dashboard y las incidencias tienen
      contenido y que el enlace de portal que imprimió el comando abre la estancia. Después
      **un segundo `make demo-reset`** y comprobar que la contraseña vuelve a valer aunque se
      haya cambiado por medio (R2.2) y que el tenant `AutoHostAI Dev` no ha cambiado (R1.5).
      El navegador necesita `make up PORT_OFFSET=<n>` si esto se hace desde un worktree.

      **Ejecutada el 2026-08-24** con `make up PORT_OFFSET=20` (el 0 lo tiene el principal y el 37
      `cleaner-photo-requirements`), y `FRONTEND_BASE_URL=http://localhost:3020` en el `.env` local
      —hace falta, porque el enlace que imprime el comando se compone con esa variable y con el
      valor por defecto apuntaría a un puerto que en un worktree no existe—. `DEMO_ACCOUNT_PASSWORD`
      de 18 caracteres. Resultados:

      - `make bootstrap` → 1 tenant, 1 config, 2 usuarios. Se le añadió `make seed-demo` (104 filas
        en 17 tablas del tenant de trabajo): sin sembrarlo, R1.5 se probaría contra 4 filas.
      - `make demo-reset` → código 0, las diez fases (`configuration → refusal → prepare →
        bootstrap → scope → delete → converge → seed → storage-sweep → clear-lock`) y el enlace de
        portal por la salida.
      - **Login y contenido**: entrada con `owner@demo.autohostai.test`; el panel trae las dos
        viviendas con sus estados (`Libre y lista`, `Mantenimiento requerido`), los recuentos de
        incidencias abiertas (1 y 2) y la estancia activa `SEED-AIRBNB-1` con fechas ancladas al
        día (22–25 ago); `/incidents` trae las tres con severidad, estado, categoría y origen.
        Único error de consola en toda la sesión: un 404 de `favicon.ico`.
      - **El enlace de portal abre la estancia**: «Redes 11», 2026-08-22 → 2026-08-25.
      - **Convergencia (R2.2), probada con el fallo real delante**: un visitante cambió la
        contraseña por `POST /auth/change-password` (204) y la publicada pasó a dar **401**
        mientras la suya daba 200. Tras el segundo `make demo-reset`, la publicada vuelve a dar
        **200 en las cuatro cuentas** y la del visitante da 401; su sesión viva, guardada sin usar,
        responde **401 `INVALID_TOKEN`** (revocación de 4.1). El enlace de portal del reset
        anterior queda en **404** y el nuevo en 200 — el borrado vacía `guest_access_tokens`, así
        que cada reset publica uno fresco y mata el previo.
      - **R1.5**: fotografía de **todas** las filas del tenant de trabajo (recuento + md5 por
        tabla, 32 tablas) sobre conexión **sin marcar** —sobre una marcada al tenant de
        demostración el listener filtraría hasta el `select` y la comprobación no podría fallar—,
        antes y después del reset: **idéntica**, 113 filas.

      **Un hallazgo que conviene no perder, y que no es del change**: la primera medición de R1.5
      salió DIFIERE (`access_records` 0→3, `audit_logs` +3, `timeline_events` +3 y el `md5` de
      `reservations` movido). No lo escribió `demo_reset`: son filas `ACCESS_RECORD_CREATED` **sin
      actor**, de la tarea programada `provision_access_records`, que da un registro de acceso a
      toda reserva confirmada **de todos los tenants** y que el `beat` de este stack disparó entre
      las dos fotografías. La medición limpia se hizo con `beat` y `worker` parados y en ventana
      cerrada. Quien repita esta verificación tiene que parar el planificador o la leerá como una
      fuga de aislamiento que no existe.
- [x] 11.5 Cobertura de requisitos, comprobada al terminar: R1.1 (5.1), R1.2 (2.1, 2.2),
      R1.3 (4.1), R1.4 (2.3), R1.5 (3.1, 3.2, 3.3, 3.4, 3.5), R2.1 (1.1, 1.2, 2.2, 8.1),
      R2.2 (4.1, 4.2, 8.3), R2.3 (2.2), R2.4 (4.1, 4.3), R2.5 (2.4, 6.3),
      R3.1 (3.5, 5.0, 5.1, 7.1), R3.2 (2.3, 3.1, 3.4), R3.3 (5.3), R3.4 (2.4, 5.0, 5.1),
      R3.5 (5.2), R3.6 (3.1), R4.1 (6.1, 6.2), R4.2 (6.1, 6.2), R4.3 (6.3, 9.5),
      R4.4 (6.1, 6.3, 6.4), R5.1 (9.1), R5.2 (9.1, 9.4), R5.3 (9.1, 9.4),
      R5.4 (8.1, 8.2, 8.3, 9.2), R5.5 (2.4, 9.2, 9.3, 9.5), R5.6 (8.1, 8.2, 9.1), R6.1 (10.1),
      R6.2 (10.1, 10.2), R6.3 (10.1, 10.2).
      **Comprobado mecánicamente el 2026-08-24**, no a ojo: un recorrido de las 37 tareas leyendo
      sus etiquetas `[R…]` y su casilla, cruzado contra este mapa. **Los 29 requisitos tienen al
      menos una tarea hecha.** La única tarea sin marcar es 8.3, y la citan R2.2 y R5.4, que se
      sostienen sobre 4.1/4.2 y 8.1/8.2/9.2 respectivamente — ningún requisito depende sólo de
      ella, así que su aplazamiento post-merge no deja ninguno descubierto.

      El cruce encontró **tres omisiones reales en este mapa, ya corregidas arriba**: `5.0` faltaba
      en R3.1 y R3.4 y `3.5` en R3.1 —la tarea 5.0 nació durante `run`, como enmienda de D10bis, y
      el mapa se escribió antes de que existiera—, y `8.3` faltaba en R5.4 aunque su propia
      etiqueta la declara. El rango `R1.5 (3.1-3.5)` se ha desplegado a las cinco tareas, para que
      el cruce no dependa de interpretar un guion.
