# Design: demo-user

## Context

`backend/app/cli/bootstrap.py` crea tenant + config + `TENANT_OWNER` + `PROPERTY_MANAGER`,
anclando su idempotencia en `BOOTSTRAP_TENANT_NAME`, y es **convergente sólo en
`storage_type`** (su D10); para usuarios es *create-only* (`if existing is not None:
continue`). `backend/app/cli/seed_demo.py` (1.780 líneas) completa ese tenant con el dataset de
PRD §27 y hace correr el reloj; su `apply_plan(session, plan, hasher, *, now)` recibe el plan ya
construido, resuelve el tenant **por nombre**, llama a `bind_session_to_tenant` y termina con un
único `uow.commit()`. Ninguno de los dos siembra conversaciones ni tokens de portal.

El listener `_scope_statement_to_tenant` de `backend/app/core/db.py` añade
`tenant_id = <marcado>` a **todo SELECT/UPDATE/DELETE del ORM** sobre las 27 clases con
`tenant_id`, y declara sus cinco límites: no cubre INSERT, ni Core/`text()`, ni el identity map,
ni las cuatro tablas hijas sin `tenant_id` (`messages`, `cleaning_checklist_completions`,
`cleaning_photos`, `review_response_drafts`). Casi todas las claves ajenas del esquema son
`ondelete="RESTRICT"` (51 declaraciones en `backend/app/*/infrastructure/models.py`), así que un
borrado por tenant no puede ir en cualquier orden.

En el lado remoto, `.github/workflows/deploy-dev.yml` tiene un job `runs-on: [self-hosted, dev]`
que resuelve secretos del OCI Vault **por nombre determinista** (`autohostai-${ENV}-<clave>`,
`--auth instance_principal`) y renderiza el `.env` de `docker-compose.deploy.yml`. Ese `.env`
**no contiene ninguna variable `BOOTSTRAP_*` ni `SEED_*`**. La policy IAM de
`infra/environments/dev/main.tf:237` enumera los OCID de los secretos legibles uno a uno, en un
único `statement`.

## Decisions

### D1 — Un comando, convergente, que aprovisiona y resetea por el mismo camino

**Chosen:** un módulo nuevo, `backend/app/cli/demo_reset.py` (`make demo-reset`), que sobre un
tenant de demostración inexistente lo aprovisiona y sobre uno existente lo resetea, ejecutando
en los dos casos la **misma** secuencia de fases. Es lo que hace que R3.3 —«un estado
indistinguible del que produce un aprovisionamiento desde cero ese mismo día»— sea una propiedad
del código y no una comprobación: no hay dos caminos que puedan divergir.

Rejected: dos comandos (`provision` + `reset`) — duplica la composición de planes y deja R3.3 a
merced de que nadie los desincronice.
Rejected: banderas de subcomando en un solo módulo — la misma divergencia con más superficie de
CLI.

### D2 — El nombre del tenant y las cuatro direcciones son **constantes del módulo**, no configuración

**Chosen:** `DEMO_TENANT_NAME = "AutoHostAI Demo"` y las cuatro direcciones
`owner|manager|cleaner|technician@demo.autohostai.test` son constantes de
`app/cli/demo_reset.py`, del mismo modo que `SEED_PROPERTIES`, `AIRBNB_PMS_ID` y `_CHECKLIST_ITEMS`
ya son constantes de `seed_demo.py`. **No existe ningún parámetro, variable de entorno ni
argumento por el que este comando pueda nombrar otro tenant.**

Esto es lo que satisface R1.4 y R3.2, y las satisface **por construcción y no por comparación**.
La alternativa evidente —«refusa si el nombre coincide con `BOOTSTRAP_TENANT_NAME`»— es
inservible precisamente en el entorno que importa: el `.env` que renderiza
`deploy-dev.yml` no lleva `BOOTSTRAP_TENANT_NAME`, así que allí la comparación se haría contra
la cadena vacía y no rechazaría nada.

Se conserva **además** una refusal explícita, porque cuesta tres líneas y cubre el único hueco
que queda: si `BOOTSTRAP_TENANT_NAME` está puesto y **es igual** a `DEMO_TENANT_NAME`, el comando
sale con código distinto de cero sin escribir nada — el caso de alguien que bautizó su tenant de
trabajo con el nombre de la demo.

Rejected: `DEMO_TENANT_NAME` como variable de entorno — convierte un invariante estructural en
un ajuste que un `-e` equivocado en un workflow puede apuntar al tenant del equipo.
Rejected: rechazo por `APP_ENV` — no distingue dos tenants dentro del **mismo** entorno, que es
el único límite que este change tiene.

### D3 — Una sola variable nueva: `DEMO_ACCOUNT_PASSWORD`, validada antes de abrir transacción

**Chosen:** `DEMO_ACCOUNT_PASSWORD` es la única configuración nueva. Se declara **vacía** en
`.env.example` (nombre sin valor) y se valida en `build_plan()` —antes de cualquier
transacción, como hacen `bootstrap.build_plan` y `seed_demo.build_plan`— contra
`PASSWORD_MIN_LENGTH` importado de `app/auth/domain/password_policy.py` (hoy 12). Un valor
ausente o corto sale con código 1 nombrando la variable, **sin ecoar el valor** (R2.1, R2.3).

No es un ajuste de `Settings` con default: se lee como los ocho `BOOTSTRAP_*`, que son `str = ""`
y se declaran obligatorios en `build_plan`. Entra en `Settings` como
`demo_account_password: str = ""`.

**No toca la regla 8 de `steering/security.md`.** Esa regla cierra en cuatro la lista de
*credenciales de proveedor externo* que viven en el entorno; `DEMO_ACCOUNT_PASSWORD` es una
contraseña de aplicación, de la misma clase que `BOOTSTRAP_OWNER_PASSWORD` y
`SEED_CLEANER_PASSWORD`, que ya viven ahí sin figurar en aquella enumeración. Lo que sí hereda
de la regla es la obligación operativa: nombre en `.env.example`, nunca un valor.

**No entra en el bloque `environment:` de ningún servicio de `docker-compose.deploy.yml`.** Se
pasa por invocación (D14), así que los contenedores de larga vida —`backend`, `worker`, `beat`—
nunca la llevan en su entorno. Es también por lo que no aplica el `${VAR:?}` de la regla 8: no
es un secreto en uso por un servicio.

Rejected: cuatro variables, una por cuenta — R2.1 contrata **una sola** contraseña para las
cuatro; cuatro variables permiten que se desincronicen.

### D4 — El borrado va por el ORM sobre una sesión **marcada al tenant de demostración**

**Chosen:** la fase de borrado ejecuta `sqlalchemy.delete(Modelo)` por el ORM sobre la sesión ya
marcada con `bind_session_to_tenant(session, demo_tenant.id)`. El listener de
`app/core/db.py` añade entonces `tenant_id = <demo>` a cada uno de esos DELETE. Eso convierte
R1.5 y R3.2 en una propiedad del mecanismo de aislamiento que el proyecto ya tiene y prueba, en
lugar de en 27 cláusulas `WHERE` escritas a mano que hay que revisar de una en una.

El orden de borrado se **deriva** de `Base.metadata.sorted_tables` invertido (orden topológico
de claves ajenas, al revés), no de una lista escrita a mano: con 51 claves ajenas
`RESTRICT`, una lista literal se rompe la próxima vez que alguien añada una tabla, y se rompe en
tiempo de ejecución sobre el entorno público. Un test asegura que el conjunto de tablas que la
fase recorre es **exactamente** el de `tenant_scoped_classes()` menos la lista de exclusión de
D5, de modo que una tabla nueva sin decisión explícita pone el test en rojo en vez de quedarse
sin borrar en silencio.

Consecuencia buena que conviene dejar escrita: las filas de `webhook_events` con `tenant_id`
`NULL` —las que §7.26 registra sin poder atribuir— quedan **fuera** del borrado sin necesidad de
excluirlas, porque una sesión marcada las filtra a cero (es el mismo hecho que pinea
`tests/test_tenant_filter.py::test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`).

Rejected: `TRUNCATE ... CASCADE` — es Core/`text()`, así que el listener no lo ve, y `CASCADE`
no tiene noción de tenant: borraría el tenant de trabajo.
Rejected: borrar la fila de `tenants` y dejar que cascadeen las demás — las claves ajenas son
`RESTRICT`, no `CASCADE`, y donde hay `SET NULL` (`audit_logs.actor_user_id`) destruiría
justo lo que R3.6 protege.
Rejected: `DELETE` en Core con `WHERE tenant_id` explícito — funciona, pero renuncia a la red
que el proyecto declara como su defensa en profundidad para pagar el mismo precio.

### D5 — Lo que el reset **no** borra: `tenants`, `tenant_configs`, `users`, `audit_logs`

**Chosen:** cuatro tablas quedan fuera del borrado, cada una por un motivo distinto y no por
comodidad:

| Tabla | Por qué se conserva |
|---|---|
| `tenants` | No lleva `tenant_id`, no es una clase con scope, y borrarla es aprovisionar de nuevo, no resetear. |
| `tenant_configs` | Otros módulos suponen que un tenant siempre tiene su config; `bootstrap.apply_plan` la converge (su D10). |
| `users` | R2.2 exige **converger** la contraseña de cuatro cuentas: si el reset las borrase y recreara, la convergencia sería un efecto colateral del borrado y no una operación, y R2.2 dejaría de estar probada. |
| `audit_logs` | R3.6. Y no basta con conservar sus filas: `audit_logs.actor_user_id` es `ondelete="SET NULL"`, así que borrar `users` dejaría el registro sin el «quién», que es la mitad por la que existe. Conservar las dos es lo mismo que conservar una. |

Todo lo demás de las 27 tablas con `tenant_id` se borra, incluidas `user_sessions` y
`password_reset_tokens`: lo que un visitante dejó abierto no debe sobrevivir al reset.

### D4bis — Enmienda a D4 y D5, del panel de la sección 3 (2026-08-23)

Tres cosas que el diseño daba por hechas y no lo estaban. El panel de seguridad capturó el SQL
**emitido** en vez de razonar sobre el listener, y de ahí salieron las dos primeras.

**1. La precondición de D4 era una frase, no código.** Las 24 sentencias de tabla con scope toman
su predicado `tenant_id` **enteramente** del marcador de la sesión: `delete(GuestModel)` sobre una
sesión sin marcar compila a un `DELETE FROM guests` pelado. Así que una sesión sin marcar no falla
— vacía esas 24 tablas **de todos los tenants de la base**, mientras las cuatro sentencias que
llevan su propio `WHERE` siguen acotadas, dejando el destrozo a medias. Y una sesión marcada a
otro tenant partiría el borrado en dos. `bind_session_to_tenant` no puede detectarlo: valida el
marcador contra sí mismo, nunca contra el tenant que el llamante dice estar borrando, que aquí es
un parámetro.

Se añade por eso `require_session_bound_to(session, tenant_id, write=...)` en
`app/core/db.py` —tiene que vivir ahí, porque `tests/test_session_marking.py` prohíbe tocar
`session.info` en `app/` fuera de ese módulo—, con sus dos excepciones nuevas en
`app/core/tenancy.py`. Es el espejo de `require_unmarked_session`, y la asimetría entre los dos
merece quedar escrita: una lectura sin scope sobre una sesión marcada responde de **menos** de lo
que debe, y suele ser una respuesta equivocada; una escritura acotada-por-marcador sobre una
sesión sin marcar toca **más** de lo que debe, y eso es pérdida de datos de todos los tenants.

**2. `users` se preservaba en bloque, y eso contradecía el último párrafo de D5.** La credencial
publicada del `TENANT_OWNER` tiene `MANAGE_USERS`, así que un visitante puede `POST /users` y
dejar una cuenta con una contraseña que sólo él conoce; las cuentas se desactivan, nunca se
borran, así que nada la reclama. Sobrevivía a todos los resets —contra «lo que un visitante dejó
abierto no debe sobrevivir al reset» y contra R3.3— y, como las direcciones son únicas en toda la
instalación (ADR 0005), **ocupaba para siempre** la dirección que le hubieran puesto, incluida la
de un futuro compañero. Se enmienda: se conservan las **cuatro direcciones constantes** y se borra
todo lo demás del tenant de demostración. Va **después** del bucle, porque
`cleaning_photos.uploaded_by` e `incident_photos.uploaded_by` son `RESTRICT`. Sus filas de
`audit_logs` sobreviven con `actor_user_id` a NULL por el `ondelete` de la columna, que es el
canje correcto: el registro de lo que pasó sobrevive a la identidad desechable que lo hizo.

**3. Lo que R3.6 conserva, y lo que no dice D5.** `audit_logs.entity_type`/`entity_id` es un par
polimórfico **sin clave ajena**, así que tras el borrado cada fila de auditoría del tenant de
demostración apunta a un id que ya no existe. No es exposición —no hay ningún endpoint que lea esa
tabla, y `REDACTED_FIELDS` impide que `changes` lleve un secreto de la regla 3— pero sí es la
**única** cosa que un reset no devuelve a un estado «indistinguible de un aprovisionamiento desde
cero» (R3.3), y es la única tabla del tenant que crece sin límite en un entorno anunciado como
reseteado a diario. Queda dicho aquí en vez de descubrirse; acotarlo con una retención es una
decisión futura y no de este change.

### D6 — Las tres tablas hijas sin `tenant_id` se borran por su padre

**Chosen:** `messages`, `cleaning_checklist_completions` y `cleaning_photos` no tienen
`tenant_id`, así que el listener no las alcanza (límite 5 de `app/core/db.py`). Se borran con un
`DELETE ... WHERE <fk> IN (SELECT id FROM <padre> WHERE tenant_id = :demo)` sobre su padre con
scope —`conversations`, `cleaning_tasks`, `cleaning_tasks`—, que es el mismo patrón que la regla
obliga a sus repositorios («debe unir el padre con scope explícitamente y traer su propio test de
aislamiento»). `review_response_drafts` es la cuarta de esa lista y también se borra por
`reviews`, aunque hoy nadie escriba en ella: dejarla fuera sería una tabla no cubierta esperando
a su primer escritor.

### D7 — Una sola transacción: borrado + convergencia + siembra

**Chosen:** las tres fases que escriben comparten sesión y **no** commitean por separado; el
único `commit` es el que ya hace `seed_demo.apply_plan` al final de su fase de reloj. Así R3.4
—«sin cambios parciales»— no necesita código propio: un fallo en cualquier fase revierte también
el borrado.

El orden importa y es: **borrar → converger la contraseña → sembrar**. Converger *antes* de
sembrar es lo que permite que quepa en la misma transacción, porque `seed_demo.apply_plan`
commitea al terminar y cualquier escritura posterior sería una segunda transacción.

`bootstrap.apply_plan` **queda fuera de esa transacción**, porque hace `session.commit()` por su
cuenta. Corre antes, en su propia transacción, y sólo tiene efecto la primera vez (crea tenant,
config, owner y manager); en un reset es un no-op que no escribe nada. Se acepta y se declara:
R3.4 gobierna el reset, y en un reset esa fase no cambia nada.

Rejected: refactorizar `bootstrap.apply_plan` para que acepte un `UnitOfWork` — cambia la
frontera transaccional del único camino de entrada a un entorno recién desplegado, por una
ganancia que en la fase de reset es nula.

### D8 — La convergencia de la contraseña vive en el comando de la demo, **no** en `bootstrap`

**Chosen:** `bootstrap.apply_plan` sigue siendo *create-only* para usuarios y
`sdd/specs/auth-tenancy.md` R7 **no cambia**. La convergencia la hace `demo_reset.py`, acotada a
las cuatro cuentas cuyas direcciones son constantes de D2 y sobre una sesión marcada al tenant
de demostración.

**Esto enmienda la lista de *Affected specs* del proposal**, que anunciaba
`sdd/specs/auth-tenancy.md` como modificada porque «R2.2 lo vuelve convergente en la
contraseña». Hacerlo allí tendría un radio de daño que el proposal no pesó: `make bootstrap` es
el comando que el RUNBOOK manda ejecutar contra el entorno desplegado, y volverlo convergente en
contraseñas significa que una re-ejecución **reescribe las contraseñas del equipo** en
`AutoHostAI Dev` con lo que haya en `BOOTSTRAP_*_PASSWORD`. R2.4 dice literalmente que la
contraseña conocida no se aplica a ninguna cuenta fuera del tenant de demostración y que eso hay
que comprobarlo en vez de confiarlo; poner la convergencia en `bootstrap` la pondría en el único
sitio del árbol que escribe contraseñas en los dos tenants.

Rejected: `bootstrap.apply_plan` convergente en contraseñas — arriba.
Rejected: un `--converge-passwords` opcional en `bootstrap` — una bandera que sólo un llamante
usa es la misma función en el sitio equivocado.

### D9 — La convergencia copia el precedente de `reset_password.py`, paso por paso

**Chosen:** para cada una de las cuatro cuentas, con el `tenant_id` de la fila comprobado
contra el id del tenant de demostración **antes** de escribir (R2.4, «comprobarlo en vez de
confiarlo»):

1. `user.set_password_hash(await hasher.hash(password), temporary=False)` — `temporary=False`
   es R1.3: operativas al instante, sin cambio forzado.
2. `users.apply_changes(tenant_id, user.id, {"password_hash": ..., "must_change_password": ...})`.
3. Una fila de `AuditLog` con `action=actions.USER_PASSWORD_RESET`,
   `changes=ChangeSet(actions.ENTITY_USER).redacted("password")` y **sin actor**
   (`actor_user_id=None`, `actor_ip=None`).
4. `SqlAlchemySessionRepository.revoke_all_for_user(..., SessionRevokedReason.PASSWORD_RESET)`
   — una convergencia que dejara vivas las sesiones del visitante anterior no habría restaurado
   la cuenta, le habría añadido una credencial.
5. **Fuera de la transacción y después del commit**, `clear_lock(user_id)` sobre
   `RedisLoginThrottle`, que es exactamente lo que `reset_password.clear_lock` documenta:
   Redis y Postgres no comparten transacción, así que uno tiene que poder fallar solo. Un
   cerrojo que caduca por sí mismo en 15 minutos sobre una cuenta ya convergida es la
   degradación benigna. Efecto lateral buscado: el bloqueo por 10 fallos consecutivos deja de
   ser permanente en un entorno con credenciales publicadas.

> **Dos enmiendas a D9, del panel de seguridad de la sección 4 (2026-08-23).**
>
> **1. La convergencia escribe también `status` y `role`, y sin eso R1.3 la derrota cualquier
> visitante.** D9 enumeraba dos columnas (`password_hash`, `must_change_password`). Pero la
> credencial publicada del `TENANT_OWNER` tiene `MANAGE_USERS`, así que un visitante puede
> `POST /users/{id}/deactivate` sobre la gestora, la limpiadora o el técnico. `users` lo preserva
> D5, la poda de D4bis sólo borra direcciones **fuera** de las cuatro, y `bootstrap.apply_plan` es
> *create-only* — de modo que la contraseña se escribiría sobre una fila `INACTIVE`, el login la
> rechazaría y el reset saldría con código 0 diciendo que ha ido bien. **Tres de las cuatro
> credenciales publicadas, matables para siempre y en silencio.** Un cambio de rol tiene la misma
> forma. Se escriben directas y **no** por `user.change_status` / `user.change_role`: esos métodos
> codifican *quién puede decidir* —rechazan el auto-cambio y limitan `GRANTABLE_ROLES`, que excluye
> `TENANT_OWNER`—, y eso son reglas de autorización de un actor interactivo; este comando no tiene
> actor, y devolver una constante a su valor declarado no es nadie ejerciendo un permiso.
>
> **1bis. Y converger `role` metió a la fase dentro de la regla 9, que antes no la alcanzaba**
> (segunda ronda del mismo panel). La regla dice «**AuditLog** para: […] **roles de User**», y la
> única fila que la fase emitía era `USER_PASSWORD_RESET` con `redacted("password")`: la
> degradación del visitante y su corrección por el reset eran las dos invisibles. El razonamiento
> de la enmienda anterior —«su enumeración cubre roles de User, no credenciales»— era cierto
> **antes** de este arreglo y dejó de serlo con él, y no se releyó. Ahora la fila lleva el diff
> real de `role`, `status`, `name` y `phone`, y la acción es `USER_ROLE_CHANGED` cuando el rol se
> mueve —filtro indexado en vez de consulta JSONB, la misma elección que ya hizo
> `user_admin.py`— y `USER_PASSWORD_RESET` cuando no. De paso desaparece un defecto menor: antes
> escribía fila de auditoría aunque no hubiera cambiado nada.
>
> **1ter. `name` y `phone` no son cosméticos: son el único canal de desfiguración duradera del
> tenant.** `PATCH /users/{id}` acepta los dos de un actor con `MANAGE_USERS`, que es lo que la
> credencial publicada del propietario tiene, y **estas cuatro filas son el único contenido
> escribible por un visitante que el reset conserva** — todo lo demás lo vacía la fase de
> borrado. Sin restaurarlos, un visitante renombra a la propietaria de la demo a un texto de
> *phishing* una vez y **ningún reset lo quita nunca**: cada visitante posterior lo lee como si lo
> hubiera escrito el producto (R3.3). Se restauran los cuatro nombres declarados y se pone `phone`
> a `NULL`. `preferred_language` se deja: es `^(es|en)$`, cualquiera lo cambia de vuelta y no
> transporta texto del atacante.
>
> **1quater. Y se escriben por la entidad, no a pelo — la razón que se dio para evitarla era
> falsa.** Aquella nota decía que `GRANTABLE_ROLES` excluye `TENANT_OWNER`; no lo excluye, es
> `frozenset(UserRole) - {SUPER_ADMIN}`. Sin actor, la guardia de auto-cambio tampoco salta, así
> que `change_role`/`change_status`/`update_profile` funcionan — y devuelven **si** el valor se
> movió, que es justo lo que el diff de auditoría de 1bis necesita. Es el mismo defecto que la
> primera redacción de D18.1: una justificación apoyada en una propiedad que el código no tiene.
>
> **1quinquies. La fase toma ahora el cerrojo de población** (`lock_tenant_for_admin`), porque
> escribe las columnas sobre las que se cuenta. `user_admin.py` lo toma antes de
> `count_active_owners_excluding` por el motivo que dice su docstring, y sin él un `PATCH` que
> corra a la vez que el job nocturno puede desactivar a la propietaria mientras cuenta como «otra
> propietaria activa» a una gestora que esta fase está a punto de degradar, dejando el tenant sin
> ningún `TENANT_OWNER` activo. Es de carrera, del tenant de demostración y se cura al día
> siguiente; se cierra igual porque cuesta una línea.
>
> **2. El efecto lateral que la cláusula 5 anunciaba no existe.** Decía que «el bloqueo por 10
> fallos consecutivos deja de ser permanente»: nunca fue permanente. `RedisLoginThrottle` pone
> `login:lock:<uid>` con TTL de `login_lockout_minutes` (15 por defecto), así que se limpia solo y
> `clear_login_locks` únicamente lo adelanta. El límite real, que ninguna decisión nombraba:
> **cualquiera en internet** puede bloquear las cuatro cuentas de demostración durante quince
> minutos con unos cuarenta intentos fallidos, y repetirlo indefinidamente, porque las cuatro
> direcciones son constantes publicables. El reset diario no mitiga nada ahí. Es sólo
> disponibilidad, acotado al tenant de demostración, y **se acepta** — pero se acepta dicho, no por
> omisión.

Sobre el punto 3 y la regla 9 de `steering/security.md`: esa regla **no obliga** a auditar un
cambio de contraseña —su enumeración cubre «roles de User», no credenciales—, así que esta fila
no es una excepción a nada y no hay que ampliar ninguna lista. Se escribe igual porque
`reset_password.py` la escribe, y por lo mismo que aquél declara: lo que distingue este comando
de un `UPDATE` a mano es que pasa por la entidad, revoca las sesiones, levanta el cerrojo y deja
rastro.

Rejected: convergir sólo si el hash difiere — comparar bcrypt exige verificar la contraseña en
claro contra el hash de cada cuenta, así que es más trabajo criptográfico y no menos, y
`set_password_hash` con la misma contraseña produce un hash distinto (sal nueva) de todos modos.
Rejected: no revocar sesiones — deja al visitante anterior dentro después de un reset que dice
haber devuelto el entorno a su estado inicial.

### D10bis — Enmienda a D10: `seed_demo.apply_plan` recibe sus lecturas sin scope ya resueltas

**Detectado y decidido en la sección 3 de `/sdd:run` (2026-08-23).** D4, D7 y D10 no podían
sostenerse las tres a la vez, y nada en el diseño lo delataba:

- **D4** manda borrar por el ORM sobre una sesión **marcada** con `bind_session_to_tenant`.
- **D7** manda que `delete → converge → seed` compartan sesión y **una** transacción.
- **D10** manda reutilizar `seed_demo.apply_plan` **tal cual**.

Pero `seed_demo.apply_plan` **empieza** con lecturas sin scope —un `find_by_email_globally` por
cuenta— y sólo **después** marca la sesión. Esas lecturas pasan por
`require_unmarked_session`, que lanza `TenantMarkedSessionError` sobre una sesión marcada
(comprobado en el contenedor, no razonado). Y `bind_session_to_tenant` es **de un solo sentido a
propósito**: su guardia contra el *unbind* existe precisamente para que nadie apague el filtro a
mitad de sesión. Así que marcar para borrar envenena la fase de siembra, en la misma sesión.

**Resolución elegida por el usuario:** se enmienda **D10**, no D4 ni D7. `seed_demo.apply_plan`
gana un parámetro opcional con el diccionario de cuentas ya resuelto (`known_accounts`), con
`None` por defecto — así `make seed-demo` se comporta exactamente igual y sigue resolviéndolo él
mismo—, y `demo_reset` lo resuelve **antes de marcar la sesión** y se lo pasa. La secuencia
queda: refusal → bootstrap → resolver cuentas (sin marcar) → **marcar** → delete → converge →
seed. El `bind_session_to_tenant` interno de `seed_demo` pasa a ser un no-op, porque marca el
mismo tenant.

Lo que esto conserva es lo que el proposal llama «la única barrera real»: el borrado sigue yendo
por el ORM sobre una sesión marcada, así que el listener de `app/core/db.py` sigue siendo lo que
acota las 24 tablas, y R3.4 conserva su transacción única.

Rechazado: borrar en Core con `WHERE tenant_id` explícito sobre una sesión sin marcar — es la
alternativa que D4 ya había rechazado, y elegirla aquí habría cambiado la barrera por 24
cláusulas escritas a mano para no tocar un módulo compartido.
Rechazado: dos transacciones (borrado marcado aparte, luego converge+seed) — enmienda R3.4, y un
fallo en `seed` dejaría el tenant de demostración vacío y sin sembrar en un entorno público hasta
la ejecución del día siguiente.

Consecuencia buena y no buscada: la fase `converge` ya no necesita `find_by_email_globally`.
Sobre la sesión marcada resuelve sus cuatro cuentas con una lectura del ORM que el listener acota
al tenant de demostración, de modo que **estructuralmente** no puede devolver la fila de otro
tenant — y la comprobación explícita de `tenant_id` que R2.4 exige («comprobarlo en vez de
confiarlo») se queda igualmente, encima.

### D10 — Las conversaciones y el token de portal se añaden a `seed_demo.py`, no al comando de la demo

**Chosen:** R4 se implementa **dentro de `app/cli/seed_demo.py`**, en su fase de reloj, así que
`make seed-demo` en local también los produce. Es lo que el proposal contrata en *Affected
specs* (`seed-data-demo.md` «gana las conversaciones y el enlace de portal de R4») y lo que
mantiene el comando de la demo delgado: su trabajo propio es el borrado, la convergencia y las
constantes.

- **Conversaciones (R4.1, R4.2, R4.4)**: una conversación por la vía canónica
  (`CreateConversationUseCase`, anclada a la estancia activa, su vivienda y su huésped) y sus
  mensajes por `ProcessInboundGuestMessageUseCase`, que es «la vía real de entrada» —clasifica,
  persiste el `Message` con su intent, escribe `GUEST_MESSAGE_RECEIVED` en el timeline, evalúa
  la política de escalado y responde o escala—. **Dos mensajes como mínimo**, elegidos para que
  el hilo enseñe las dos ramas que R4.1 nombra: uno de intent reconocido y respondible, que el
  `MockAIAdapter` contesta desde su catálogo de plantillas, y uno que dispara
  `EscalationReason.EMERGENCY_KEYWORD` (evaluado por `contains_emergency_keyword`, sin depender
  del clasificador), que escala a persona. El adaptador es `MockAIAdapter`, determinista, sin
  estado, sin I/O y sin credenciales de proveedor — R4.2 cumplida por la misma pieza que el
  router ya inyecta.
- **Enlace de portal (R4.3)**: `IssueGuestAccessTokenUseCase` sobre la reserva `SEED-AIRBNB-1`
  (la estancia activa), que devuelve el token en claro **una sola vez**. Se le pasa un
  `CallerOwnedUnitOfWork`, como el propio módulo ya importa, para que su `commit()` no rompa la
  transacción única de D7. La URL se compone `{frontend_base_url}/guest/{token}` y **se imprime**
  — ver D19.
- El texto de los mensajes son **constantes del módulo**, en el idioma del tenant, igual que
  `_CHECKLIST_ITEMS` y los títulos de `SEED_INCIDENTS`.

### D11 — Regla 11: `messages.content` gana un cuarto escritor, y la fila va en un solo sitio

**Chosen:** este change añade un escritor a `messages.content`, columna ya censada por
`messaging-ai` con tres escritores y tres contratos. El cuarto es el seed, y su contrato es el
tercero que `seed-data-demo-extension` ya declaró para `incidents.title`/`description`:
**constantes del módulo**, catálogo cerrado por disciplina y no impuesto en código.

La fila nueva se escribe **en la tabla de la regla 11 de `sdd/steering/security.md` y en ningún
otro sitio**, con su propio test. `backend/tests/test_rule11_ownership.py` recorre `sdd/`,
`docs/`, `backend/app/`, `backend/alembic/versions/` y `backend/tests/` y se pone en rojo
nombrando fichero y línea si un bloque atribuye el escritor de una columna censada fuera de esa
tabla. Este documento está exento porque el guardián excluye `sdd/changes/` entero; **el fichero
de spec viva que `/sdd:archive` escriba no lo está**, así que ni `sdd/specs/demo-tenant.md` ni
`sdd/specs/seed-data-demo.md` pueden repetir la atribución.

### D12 — La contraseña llega al Vault sin pasar por el repositorio ni por un secret de Actions

**Chosen:** `infra/environments/dev/main.tf` gana un `oci_vault_secret` nuevo,
`secret_name = "autohostai-${var.env}-demo-account-password"`, cuyo contenido inicial es un
`random_password` (longitud 24, ≥ `PASSWORD_MIN_LENGTH`) y que lleva
`lifecycle { ignore_changes = [secret_content] }`. Y su OCID entra en el **mismo** `statement` de
`oci_identity_policy.dev_runner_read_secrets` en el **mismo apply que lo crea**, que es
literalmente la mitigación que `object-storage-provisioning` declaró para sus cuatro: olvidarlo
hace fallar el paso de lectura del Vault nombrando la clave, que es el comportamiento correcto y
un viaje de ida y vuelta evitable.

Con eso R5.4 se cumple al pie de la letra —el valor no está en el repositorio ni en un secret de
Actions—, R5.6 también —el secreto y el permiso son código—, y R2.1 igual: el valor nace
generado, no de un default en el árbol.

**El valor que se publica es uno elegido por una persona, puesto out-of-band** (decidido en el
gate del 2026-08-23): `oci vault secret update-base64`, documentado en el RUNBOOK, el mismo canal
out-of-band que la regla 8 de `steering/security.md` acepta hoy para la clave SSH. `ignore_changes`
es exactamente lo que lo hace sobrevivir al siguiente `apply`. El `random_password` de la creación
no es la contraseña publicada: es el valor con el que el recurso nace para que **nunca** haya un
default en el árbol, y para que un entorno recién aplicado tenga credenciales inertes en lugar de
conocidas hasta que alguien las fije.

**Su forma, acordada en el gate: una frase corta y dictable por teléfono, del orden de 15
caracteres, con guiones** — legible para una persona, y **por encima de `PASSWORD_MIN_LENGTH`**,
que es lo que deja R2.3 intacta y permite que un visitante que cambie la contraseña vuelva a
ponerla desde `POST /auth/change-password`. Se descartó explícitamente una palabra sola de 10
caracteres: habría exigido enmendar R2.3, y habría dejado a la cuenta que alguien cambiase con una
contraseña que nadie conoce hasta el reset del día siguiente.

**El valor concreto no se escribe en ningún fichero del repositorio, y esto incluye este
documento.** No es celo de más: `sdd/changes/` se archiva y queda en el histórico de git para
siempre, así que un valor escrito aquí sobrevive a su propia rotación y le da a quien lo lea
después una contraseña plausible y equivocada. Su único hogar es el Vault; `docs/demo-tenant.md`
documenta **cómo** cambiarla (R6.2), no cuál es.

Se rechazó la simplificación de dejar la contraseña como constante publicada del árbol y suprimir
el Vault entero: «el valor sigue fuera del árbol» es una de las tres cláusulas con las que el
proposal acota la inversión de seguridad de R2, y prescindir de ella para ahorrar un recurso de
Terraform habría enmendado R2.1, R5.4 y R5.6 a la vez.

Rejected: `var.demo_account_password` desde un secret de Actions, como
`var.github_app_private_key` — es exactamente lo que R5.4 prohíbe.
Rejected: valor puesto a mano en la consola de OCI sin declarar el recurso — contra la norma
IaC-first de `steering/infra.md` y contra R5.6.

### D13 — El workflow: `schedule` + `workflow_dispatch`, en el runner de la VM, compartiendo `concurrency` con el deploy

**Chosen:** `.github/workflows/demo-reset.yml`, un solo job:

```yaml
on:
  schedule: [{ cron: "15 3 * * *" }]
  workflow_dispatch:
jobs:
  reset:
    if: github.ref == 'refs/heads/main'
    runs-on: [self-hosted, dev]
    permissions: { contents: read }
    timeout-minutes: 20
    concurrency: { group: deploy-dev, cancel-in-progress: false }
```

Cada pieza responde a algo:

- **`runs-on: [self-hosted, dev]`** (R5.2): el runner ya corre **en** la VM, así que alcanza
  `postgres` por la red interna del compose. R5.3 se cumple por no hacer nada: cero puertos
  entrantes, cero SSH, `security_list` intacta.
- **`concurrency: deploy-dev`**, el **mismo grupo** que el job `deploy` de `deploy-dev.yml`:
  un reset nunca corre a la vez que un despliegue que está reescribiendo el `.env` y
  recreando contenedores. Es el único acoplamiento que este change añade al workflow existente,
  y es deliberado.
- **`if: github.ref == 'refs/heads/main'`**: `schedule` sólo dispara desde la rama por defecto,
  pero `workflow_dispatch` no, y el gating por rama de los jobs que tocan el entorno es la
  postura que `steering/infra.md` fija como requisito.
- **`03:15 UTC`, no en punto**: GitHub encola los cron a la hora en punto y la hora no es
  exacta; y a las 06:00 UTC corre `generate_price_recommendations` en el beat.
- **`::add-mask::`** sobre la contraseña en cuanto se lee del Vault, antes de cualquier otro
  paso (R5.5): es el mecanismo por el que un fallo posterior no puede volcarla en el log.
- **`actions/checkout` con `clean: false`**: el workspace del runner es el mismo directorio para
  todos los workflows del repo, y el `.env` que renderiza el deploy es un fichero **no
  versionado**. El `git clean -ffdx` del checkout por defecto lo borraría, y con él la
  interpolación de `docker-compose.deploy.yml` (que lleva `${GHCR_NS:?}`). Con `clean: false`
  sobrevive.
- **Precondición explícita antes de invocar** (R5.5): si no existe `.env`, o el stack no está
  arriba, el job falla en rojo nombrando la fase —«precondición: el entorno no está
  desplegado»— en vez de morir dentro de un error de interpolación de Compose.

Rejected: cron de máquina por cloud-init — el `metadata` de la instancia es `ForceNew` con
`ignore_changes` (`infra/environments/dev/main.tf:176-180`), así que no llegaría nunca a la VM
viva y forzarlo la recrearía.
Rejected: un job programado en `ubuntu-latest` que alcance la BD — exige publicar Postgres o
abrir SSH, contra R5.3.
Rejected: extraer el «Render .env» del deploy a un script compartido y que el reset renderice el
suyo — es la solución más limpia y es refactor de un workflow que funciona; queda como deuda
nombrada en Risks.

### D14 — La invocación: un contenedor de un solo uso sobre el stack vivo

**Chosen:**

```bash
export DEMO_ACCOUNT_PASSWORD          # leída del Vault y enmascarada en el paso anterior
docker compose -f docker-compose.deploy.yml run --rm --no-deps -T \
  -e DEMO_ACCOUNT_PASSWORD \
  -e BOOTSTRAP_STORAGE_TYPE=S3 \
  backend python -m app.cli.demo_reset
```

- **`run --rm` y no `exec`**: no depende de que el contenedor `backend` de larga vida esté
  *healthy*, y el contenedor efímero muere con la contraseña dentro. `--no-deps` evita
  re-ejecutar `migrate`; el servicio se une igualmente a la red `private` del proyecto, que es
  por donde `postgres` es alcanzable. `run` no publica los `ports` del servicio salvo con
  `--service-ports`, así que no colisiona con el `127.0.0.1:8000` del contenedor vivo.
- **`-e DEMO_ACCOUNT_PASSWORD` sin `=valor`**: pasa el valor desde el entorno del paso en vez de
  escribirlo en la línea de órdenes, donde quedaría en la tabla de procesos de la VM.
- **`-e BOOTSTRAP_STORAGE_TYPE=S3`**: el `.env` desplegado no lleva esa variable, así que sin
  esto el tenant de demostración nacería `LOCAL` mientras `AutoHostAI Dev` es `S3`, y la demo
  ejercitaría un camino de almacenamiento que el entorno no usa. `bootstrap.apply_plan` la
  converge (su D10), y explicitarla aquí es el equivalente en código del `docker compose exec -e
  BOOTSTRAP_STORAGE_TYPE=S3` que `.env.example` ya documenta como el modo de hacerlo a mano.
  En local, sin la variable, el default `LOCAL` es el correcto.
- `python -m` y no `uv run`, porque `uv` sólo existe en la etapa de desarrollo de
  `backend/devops/Dockerfile` — el mismo motivo que documentan los targets `bootstrap` y
  `seed-demo` del `Makefile`.

### D15bis — Enmienda a D15: dos fases más, `prepare` y `scope`

**Del panel de seguridad de la sección 5.** D15 enumeraba siete fases y el comando declaraba ocho
(con `clear-lock`). Faltaban dos, y no por estética: R5.5 promete que el workflow se pone en rojo
«nombrando la fase que falló», y **todo el tramo entre `bootstrap` y `delete` estaba fuera de
cualquier `_phase`** — así que un fallo ahí salía por el catch-all de `main()` diciendo «outside any
phase», que es justo lo que esa promesa excluye. Y ese tramo había acumulado tres fuentes de fallo
nuevas en una sola ronda: la lectura del almacén, el `flush()` de la convergencia de columnas del
tenant, y la precondición nueva de `collect_storage_keys`.

Las fases quedan en diez: `configuration → refusal → prepare → bootstrap → scope → delete →
converge → seed → storage-sweep → clear-lock`. `prepare` es la lectura previa a bootstrap (el
almacén tal como está **antes** de que bootstrap lo converja); `scope` es el cerrojo, la resolución
de cuentas sin marcar, el marcado, la recogida de claves y la convergencia de las columnas del
tenant. La refusal se queda fuera de toda fase a propósito, porque es código 1 y no 2.

### D15 — Fases nombradas, y un código de salida que las distingue

**Chosen:** el comando declara sus fases y las nombra en la salida y en el error
(`configuration`, `refusal`, `bootstrap`, `delete`, `converge`, `seed`, `storage-sweep`), como
pide R3.4. Códigos: `0` correcto; `1` configuración, refusal o precondición (nada escrito);
`2` fallo inesperado, imprimiendo **sólo la clase** de la excepción y nunca su detalle. Ese `2`
parco no es pereza: los errores de SQLAlchemy anexan la sentencia **con sus parámetros**, y
entre esos parámetros va un hash de bcrypt — es la misma postura que `seed_demo.main()` ya
sostiene, y es lo que hace que R2.5 y R5.5 no se contradigan.

La salida normal son recuentos por entidad y las fases recorridas. **Nunca** la contraseña, ni
su hash, ni un token.

### D16 — El barrido de objetos huérfanos ocurre **después** del commit

**Chosen:** antes de borrar filas, la fase recoge las `storage_key` de `cleaning_photos` e
`incident_photos` del tenant de demostración. Después de que el commit haya salido bien, y sólo
entonces, las borra por `FileStoragePort.delete(key)` a través de
`ConfiguredFileStorageFactory` e informa de cuántas borró y **cuáles no pudo** (R3.5).

El orden es lo importante: borrar objetos antes del commit dejaría, si algo falla y se revierte,
filas vivas apuntando a objetos que ya no están — un daño peor que el que se evita. Un fallo del
almacén **no** pone el comando en rojo: la base de datos quedó consistente, y decir que el reset
falló sería falso; se informa con una línea que nombra las claves, que es exactamente lo que
`seed_demo.apply_plan` ya hace cuando sus subidas quedan sin fila.

Se **borran** y no sólo se enumeran, aunque R3.5 pida sólo informar, porque este comando corre a
diario: seis fotos por ejecución que nadie recoge son unas 2.200 al año en el bucket de `dev`,
y un job programado que gotea objetos para siempre es un defecto operativo, no una asimetría
aceptada. Las claves son `tenants/{tenant_id}/…`, compuestas sólo por identificadores que
generó el propio sistema, así que nombrarlas en la salida no revela nada (excepción única y
nombrada de la regla 5 de `steering/security.md`, que ya cubre este caso para el seed).

### D17bis — Enmienda a D17: `users.last_login_at` no converge, y R3.3 queda matizada

**Del panel de seguridad de la sección 4 (2026-08-23), decidido por el usuario en su gate.** D17
leyó «indistinguible» sobre lo que devuelven la API y las pantallas, y dejó fuera `audit_logs`,
`users.created_at` y `users.id` argumentando que ningún endpoint los contrasta. Hay una cuarta
columna que sí se devuelve y que el reset **no** restaura: `users.last_login_at`.

Cada login de un visitante la mueve (`touch_last_login`), `user_schemas.py` la expone a cualquier
lector con `MANAGE_USERS`, y `users` lo conserva D5 — así que tras un reset las cuatro filas
llevan las marcas de sesión del visitante anterior donde una siembra desde cero muestra `NULL`. Un
visitante puede por tanto leer cuándo estuvo el anterior. Y la fase **no puede** arreglarlo por su
camino normal: `last_login_at` está en `FORBIDDEN_UPDATE_COLUMNS` de `apply_changes`, a propósito,
para que ninguna escritura ordinaria pueda falsificar historial de acceso.

**Resolución elegida: se documenta como desviación de R3.3, no se fuerza.** Lo que se descartó y
por qué: saltarse la lista blanca desde este comando habría creado la primera excepción a esa
guardia —en el único módulo que resetea un tenant entero—, y esa excepción sería el precedente
para escribir otras columnas prohibidas; y añadir un `clear_last_login` al repositorio de `auth`
habría metido superficie de producción compartida para una necesidad exclusiva de la demo. La
garantía que da la lista blanca vale más que este hueco: es un timestamp no sensible, visible sólo
dentro del tenant de demostración y sólo a quien ya tiene `MANAGE_USERS` —es decir, a quien ya
tiene las credenciales publicadas—.

**Consecuencia normativa: R3.3 se lee con esta matización y con la de D17, no sin ellas.** Lo que
el reset garantiza indistinguible es la composición del dataset, los estados operacionales, el
timeline y las fechas; lo que no, y queda enumerado: `audit_logs`, `users.created_at`, `users.id` y
`users.last_login_at`.

### D16bis — Enmiendas a D16, del panel de la sección 5 (2026-08-23)

Cuatro, y la primera es la que importa: **esta es la primera fase del change que borra fuera de la
base de datos**, en un bucket compartido por todos los tenants del entorno y sin filtro de tenant
que la salve. Un error de scope aquí no filtra, **demuele**, y a diferencia de la transacción de
Postgres no se revierte.

**1. `collect_storage_keys` no tenía precondición, y el panel de tenancy demostró lo que costaba.**
Sus dos hermanas —`delete_the_tenants_rows` y `converge_the_demo_passwords`— refusan una sesión
que no esté ligada al tenant que reciben; ésta no, y su lectura de `incident_photos` no llevaba
predicado propio: la acotaba sólo el marcador. Llamada sobre una sesión sin marcar **devolvió la
clave de `incident_photos` del vecino**, que habría entrado directa en `FileStoragePort.delete`.
Ahora lleva `require_session_bound_to`, y las lecturas que sí pueden llevar `WHERE tenant_id`
explícito lo llevan aunque el listener lo añadiría: es la lectura que alimenta un borrado
irreversible, así que no se apoya en que un listener siga enchufado.

**2. `sweep_storage` re-comprueba el prefijo de cada clave.** No es redundante con las lecturas
acotadas: es lo último que hay entre el resultado de una consulta y un borrado que no se deshace.
Y el prefijo es un invariante real y no una costumbre de nombrado —lo verificó el panel—:
`_photo_storage_key` es la única función privada por la que pasan los dos constructores públicos
de claves, y son los únicos escritores de esas columnas. Una clave fuera de `tenants/{id}/` se
**rechaza y se nombra** en el informe.

**3. El almacén se resuelve del `tenant_configs.storage_type` del tenant **antes de la fase de
bootstrap**, no de `BOOTSTRAP_STORAGE_TYPE`.** *(La primera versión de esta enmienda decía sólo lo
segundo, y el panel de seguridad de la ronda siguiente demostró que **el arreglo era inerte**:
`bootstrap.apply_plan` converge esa columna al valor del entorno **y commitea** al principio de la
propia ejecución, así que leerla después devolvía el valor del entorno por otro camino. Se había
movido la fuente, no el valor — y el test que lo cubría sólo pasaba porque `bootstrap` estaba
stubbeado, es decir afirmaba una propiedad que el comando no tenía. Leerla antes es lo que la hace
verdadera, y el test ya no necesita ningún stub.)* `seed_demo` lee esa misma columna para esta misma pregunta. La
diferencia no es académica: la fase de bootstrap converge la config al valor del entorno en la
cabeza de la propia ejecución, así que las claves recogidas pueden ser anteriores al tipo actual —
y un barrido contra el almacén equivocado **sale bien en los dos adaptadores** (el `missing_ok=True`
de LOCAL, el 204 de S3), imprimiendo «deleted 6 of 6» de una limpieza que no ocurrió mientras los
huérfanos de verdad no se nombran (R3.5).

**4. Las columnas con clave de objeto se derivan del esquema.** D16 nombraba dos tablas de fotos;
el panel encontró una tercera, `expenses.receipt_storage_key`, muerta hoy —`app/statements/` no
tiene capa de aplicación ni router— y por tanto exactamente el hueco que orfanaría objetos en
silencio el día que `revenue-statements` le diera un escritor. `storage_key_columns()` las deriva
como `unscoped_children()` deriva sus tablas, y un test las fija por valor para que la siguiente
sea una decisión de alguien y no una omisión.

**Y una corrección a la redacción de D16, no al código**: decía que nombrar las claves en la salida
invoca «la excepción única y nombrada de la regla 5». **No la invoca, y la regla 5 prohíbe
derivarse una segunda** («quien crea necesitar una segunda no la tiene»). El precedente que se
citaba dice justo lo contrario: `seed-data-demo-extension` **declinó** invocarla —«no se invoca la
excepción nombrada de la URL prefirmada, que es de otra cosa»— porque la prohibición se acota a la
**superficie de respuesta** y no alcanza a los logs. El razonamiento correcto, y el que ahora está
escrito en el código, es ése: la stderr de un CLI no es superficie de respuesta, y las claves se
componen sólo de identificadores que generó el sistema.

### D17 — Qué significa «indistinguible» en R3.3

**Chosen:** «indistinguible de un aprovisionamiento desde cero ese mismo día» se lee sobre **lo
que la API y las pantallas devuelven**. `audit_logs` queda fuera y por eso R3.3 y R3.6 no se
contradicen: `backend/app/audit/` no tiene capa `api/` —sólo `domain/` e
`infrastructure/`—, así que ningún endpoint ni ninguna pantalla lee esa tabla, y su acumulación
entre resets no es observable por un visitante. Las filas de `users` conservan su `created_at` y
su `id` originales por lo mismo: no hay endpoint que los contraste contra nada.

Lo que R3.3 sí obliga y se prueba: la composición del dataset, los estados operacionales, el
timeline y las fechas son los que produce una siembra de ese día.

### D18 — Cómo se prueba **en rojo** cada una de las tres cláusulas que la nota de R2 exige

El proposal exige que el diseño diga cómo se prueba en rojo el acotamiento de la reversión de
seguridad. Son tres, y ninguna se prueba igual:

1. **La credencial existe sólo dentro del tenant de demostración (R2.4).** Test con **dos**
   tenants en la base: el de demostración y un vecino con una cuenta cuya contraseña se conoce.
   Se ejecuta el comando y se afirma que la contraseña del vecino **sigue verificando** contra su
   valor anterior y que su `password_hash` no cambió. La lectura de verificación va sobre una
   sesión **no marcada** o marcada al *vecino*: sobre una sesión marcada al tenant de
   demostración el test no puede fallar, porque el listener filtra hasta el `select` de una
   columna y las filas del vecino vuelven vacías. En rojo: se comprueba quitando el `tenant_id`
   de la comprobación previa de D9 y viendo el test caer.
2. **El valor sigue fuera del árbol (R2.1).** Dos tests: `demo_account_password` sin valor
   por defecto en `Settings`, y `DEMO_ACCOUNT_PASSWORD=` presente y **vacía** en `.env.example`.
   El segundo lee el fichero y falla si la línea tiene valor a la derecha del `=`.
3. **El aislamiento por tenant es la única barrera, y aguanta (R1.5).** Test que fotografía
   todas las filas del tenant de trabajo antes y después del comando y afirma igualdad;
   ejecutado también en su variante de borrado, que es la fase con capacidad de daño. En rojo:
   se comprueba sustituyendo el DELETE del ORM por uno en Core sin cláusula de tenant —el
   listener deja de verlo— y viendo el test caer.

> **Enmienda medida a la cláusula 1, del panel de la sección 4 (2026-08-23).** Lo que esa
> cláusula manda —«se comprueba quitando el `tenant_id` de la comprobación previa de D9 y viendo
> el test caer»— **es falso, y se comprobó a mano en vez de suponerlo**. La fase de convergencia
> tiene cuatro capas que acotan la escritura al tenant de demostración, y se rompieron una a una
> y las tres primeras a la vez: la búsqueda por email acotada por el listener, el
> `users.get(tenant_id, …)` explícito, y el `tenant_id` que se le pasa a
> `users.apply_changes(…)`. **Con las tres rotas, los 61 tests siguen en verde.** La razón es la
> cuarta capa, que no está escrita en D9 y es la que de verdad manda: la sesión está **marcada**,
> así que el listener añade `tenant_id = <demo>` también al `UPDATE` del ORM que hace
> `apply_changes`. Ninguna cantidad de «olvidar el tenant» **dentro** de esta fase alcanza la
> fila de otro tenant.
>
> Así que el rojo de R2.4 no es el que D18.1 describía: es **ejecutar la fase sobre una sesión sin
> marcar**, y lo pinea `test_the_converge_phase_refuses_a_session_that_is_not_bound_to_the_tenant`
> — quitar `require_session_bound_to` de la fase pone ese test, y sólo ese, en rojo.
>
> **Segunda medición, y corrige a la primera** (panel de seguridad de la sección 4): el operador de
> mutación importa. **Borrar** las comprobaciones no hace nada, pero **sustituirlas** por un
> `tenant_id` ajeno sí: un `uuid.uuid4()` en `users.get(...)` pone en rojo los tests de
> convergencia —la cuenta no se encuentra y no se escribe nada—, y en `users.apply_changes(...)`
> ésos **y** el del vecino, porque su guardia de `rowcount != 1` levanta. *(Sin cifra a propósito:
> la primera redacción decía «4 y 5» y quedó obsoleta el mismo día, cuando las dos pruebas nuevas
> de R1.3 pasaron a recorrer el mismo camino. Lo que se pinea es qué mutación produce rojo, no
> cuántos.)* De modo que las tres
> comprobaciones son demostrablemente **activas**: se ejecutan y deciden. Lo que no son es
> demostrablemente **protectoras**, porque no hay forma de provocar una escritura cruzada: el
> marcado, la precondición de esta fase, el índice **global** `uq_users_lower_email` —que hace que
> «esta dirección es de otro tenant» y «el tenant de demostración tiene esta cuenta» sean estados
> mutuamente excluyentes— y el `rowcount != 1` de `apply_changes` la detienen cada uno por su
> cuenta. Se conservan las tres, y la redacción anterior de esta enmienda («no demostrable en rojo
> por separado») era **falsa**: lo era sólo para el operador de borrado.
>
> Y una consecuencia sobre los tests: `test_a_neighbours_password_is_never_touched` guarda a un
> vecino con `owner@company.example`, **una dirección que la fase nunca consulta**, así que ninguna
> mutación de una comprobación de tenant puede alcanzarlo. Se conserva como guardia de regresión
> contra una versión futura de la fase que recorra algo más ancho que sus cuatro constantes —no
> como la prueba de R2.4—, y su docstring lo dice.

A los que añade el test de refusal de D2 (con `BOOTSTRAP_TENANT_NAME == DEMO_TENANT_NAME`, el
comando sale distinto de cero y la base queda **byte a byte** igual) y el de R2.3 (contraseña de
11 caracteres → código 1 sin escribir).

### D19 — El enlace del portal se imprime, y R2.5 gana una excepción nombrada

**Chosen:** el comando imprime la URL del portal (`{frontend_base_url}/guest/{token}`) en su
salida, y el workflow la publica en su resumen. R2.5 —que prohíbe emitir «la contraseña, su hash
ni **ningún token**»— gana **una** excepción, y está acotada por tres hechos y no por una
intención:

1. es el token del **tenant de demostración**, así que lo que abre son datos de demostración y
   nada más — el aislamiento por tenant es el mismo límite que sostiene toda la reversión de R2;
2. **muere en el reset siguiente**, porque `IssueGuestAccessTokenUseCase` revoca el token vivo de
   la estancia antes de acuñar el suyo, y la estancia entera se borra en cada ejecución;
3. **no hay otro canal**: el valor en claro existe una sola vez, en el retorno de ese caso de
   uso; sólo se persiste su digest. No imprimirlo es perderlo, y con él R4.3.

Lo que la excepción **no** concede: la contraseña y su hash siguen prohibidos sin matices, y
ningún otro token del sistema entra aquí. En particular no cubre los tokens de portal que emite
la API en el tenant de trabajo, ni `password_reset_tokens`, ni las sesiones.

Consecuencia sobre el enmascarado de D13: `::add-mask::` se aplica a la **contraseña** y no a la
URL del portal, que es justamente lo que este workflow tiene que dejar leer.

Rejected: no publicarlo y documentar cómo acuñar uno con `POST
/api/v1/reservations/{id}/guest-access-token` — ninguna pantalla consume hoy ese endpoint (sólo
aparece en `frontend/lib/api/generated/openapi.d.ts`), así que el visitante tendría que usar la
API a mano para ver el portal de una demo.
Rejected: sacar R4.3 de alcance — el portal de huésped es una de las nueve superficies reales que
la aplicación sabe enseñar hoy, y es la única que un visitante puede ver sin cuenta.

### D7bis — `tenants.timezone` se converge, y es la única columna de `tenants` que debe

**Del panel de QA de la sección 5 (2026-08-23).** `PATCH /tenants/{id}` acepta `timezone` de
cualquier `TENANT_OWNER` —que es lo que la credencial publicada tiene— y `seed_demo.apply_plan`
ancla **las fechas de todo el dataset** a esa columna, calculando «hoy» en el calendario del tenant
y no en el de UTC. Así que un visitante pone una zona al otro lado de la línea de cambio de fecha
una vez, y **todos los resets siguientes fechan la demo en un día que un aprovisionamiento desde
cero nunca produciría**, informando de éxito cada vez. Rompe R3.1 («fechas ancladas al día de la
ejecución») y R3.3, y nada en el comando la leía.

**Y la comparación con `billing_email` es la que decide el criterio**, porque las dos son columnas
de `tenants` que un visitante puede escribir y sólo una se converge: la de `billing_email` falla
**cerrada** —el guardián de identidad refusa, no se escribe nada, y es un límite aceptado y
documentado (Risks, tarea 10.1)— y ésta falla **mal**. Un reset que miente sobre haber restaurado
el dataset es peor que uno que se niega a correr. Ese es el criterio: se convergen las columnas
cuyo daño es silencioso, no las que producen un rechazo visible.

`DEMO_TENANT_TIMEZONE = "Europe/Madrid"`, que es el entorno de PRD §27, y la restauración se
informa en las notas del comando.

**Enmienda a esta enmienda, del panel de QA de la ronda siguiente: el criterio tenía un tercer
caso que no nombraba, y `tenants.country` cae en él.** `PATCH /tenants/{id}` lo acepta, **nada lo
computa** —ni el seed ni el comando— y nada lo convergía. Así que no produce rechazo como
`billing_email` ni fechas equivocadas como `timezone`: produce una **desfiguración visible y
permanente** que ningún reset quita, que es exactamente la clase que `1ter` ya había cerrado para
`users.name`/`phone`. Se converge también, con `DEMO_TENANT_COUNTRY = "ES"`. El criterio queda
entonces en tres casos y no en dos: **se convergen las columnas cuyo daño es silencioso —fechas
mal ancladas o contenido desfigurado— y se dejan las que producen un rechazo visible.**

Y del mismo panel, dos correcciones de hecho:

- **`name` no bifurca la demo en silencio**, que era lo que se temía al escribir el criterio.
  Medido: renombrar el tenant hace que el guardián de identidad no encuentre nada, que
  `bootstrap.apply_plan` intente crear uno nuevo y que choque con la unicidad **global** de
  `uq_users_lower_email`, levantando `BootstrapConflictError` sin commitear nada. Cae del lado
  «falla cerrado» del criterio, y ahora tiene test.
- **La tabla de Risks nombraba la excepción equivocada** para ese síntoma (`MultipleResultsFound`);
  la real es `BootstrapConflictError`. Importa porque ese nombre es lo que buscaría quien escriba
  la entrada de runbook.
- **La nota de la restauración mentía**: se formateaba después de asignar, así que informaba del
  valor que acababa de escribir como el valor que «había». Siempre la constante, nunca lo que el
  visitante puso — el único dato que la nota existe para dar. Se lee antes de escribir, y el test
  afirma el valor viejo en vez de la palabra «timezone».

### D20 — Cadencia: diaria, 03:15 UTC

**Chosen:** `cron: "15 3 * * *"`. Fuera de la hora en punto, porque GitHub encola ahí los cron
programados y la hora no es exacta; y lejos de las 06:00 UTC en que el beat corre
`generate_price_recommendations`. Lo que un visitante acumule vive menos de 24 h, que es también
la contención de tener credenciales publicadas.

Rejected: semanal — menos huella en el bucket y en `audit_logs`, pero deja el dataset envejecer
hasta seis días y la estancia «activa» habría terminado antes de que alguien entre a verla, que
es precisamente la degradación que este change existe para impedir.

## Changes by area

| Area | Files | Change |
|---|---|---|
| CLI backend | `backend/app/cli/demo_reset.py` **(nuevo)** | Constantes del tenant y de las cuatro cuentas (D2), `build_plan` con validación de `DEMO_ACCOUNT_PASSWORD` (D3), refusal (D2), fase de borrado (D4-D6), convergencia (D9), composición con `bootstrap.apply_plan` y `seed_demo.apply_plan` (D7), barrido de objetos (D16), fases y códigos de salida (D15). |
| Config backend | `backend/app/core/config.py` | `demo_account_password: str = ""`. |
| Core backend | `backend/app/core/db.py`, `backend/app/core/tenancy.py` | `require_session_bound_to` y sus dos excepciones (D4bis). **No estaba en este diseño**: la precondición de D4 era prosa, y sin ella una sesión sin marcar convierte la fase de borrado en un vaciado de todos los tenants. |
| Seed | `backend/app/cli/seed_demo.py` | Parámetro opcional `known_accounts` en `apply_plan` y el `resolve_known_accounts` que lo produce (D10bis). Fase nueva en `_advance_the_clock`: conversación + mensajes por `ProcessInboundGuestMessageUseCase`, token de portal por `IssueGuestAccessTokenUseCase` con `CallerOwnedUnitOfWork` (D10). Nuevas claves en `created`. |
| Orquestación local | `Makefile` | Target `demo-reset` (`$(COMPOSE) exec backend python -m app.cli.demo_reset`). |
| Entorno | `.env.example` | `DEMO_ACCOUNT_PASSWORD=` (nombre sin valor) con su comentario. |
| Entorno | `docker-compose.yml` | Monta `./.env.example:/workspace/.env.example:ro` en `backend`. **Añadido en `/sdd:run`, aprobado en el gate de la sección 2 (2026-08-23)**, y no estaba en este diseño: D18.2 exige un test que **lea** `.env.example`, y el contenedor monta sólo `./backend` como `/app`, así que sin el montaje el test sólo podría correr en CI. `backend/tests/auth/test_bootstrap.py` había declinado escribir ese mismo test por exactamente este motivo —«un test que no puede correr donde corre la suite es peor que ninguno»—, así que aceptar el montaje **revierte esa decisión a conciencia** y su docstring se corrige en el mismo change. Sigue los dos precedentes ya presentes en ese bloque `volumes` (`./sdd`, `./docs`), es de sólo lectura, es dev-only —`docker-compose.deploy.yml` no lo recibe— y no toca la guardia de postura de red, que lee únicamente la clave `ports:`. |
| Terraform | `infra/environments/dev/main.tf` | `random_password.demo_account` + `oci_vault_secret.demo_account_password` con `ignore_changes`, y su OCID en el `statement` de `oci_identity_policy.dev_runner_read_secrets` (D12). |
| CI/CD | `.github/workflows/demo-reset.yml` **(nuevo)** | Workflow programado (D13, D14). |
| Steering | `sdd/steering/security.md` | Fila nueva en la tabla de la regla 11: `messages.content` ← el seed, contrato «constantes del módulo» (D11). |
| Docs | `docs/demo-tenant.md` **(nuevo)** | R6: las cuatro cuentas y qué puede cada una, qué **no** es demostrable, cómo se cambia la contraseña y qué ejecutar después, reset manual y cadencia. |
| Docs | `docs/seed-demo.md`, `docs/README.md`, `RUNBOOK.md` | Las conversaciones y el enlace de portal en el inventario del seed; enlace a `docs/demo-tenant.md`; rotación de la contraseña en el Vault. |
| Tests | `backend/tests/test_demo_reset.py` **(nuevo)**, `backend/tests/test_seed_demo*.py` | D18 y la cobertura de la fase nueva del seed. |

## Data & interfaces

**Esquema**: ninguna migración. Ni una columna, ni una tabla, ni un índice. Todo el change se
apoya en el esquema que ya existe — es lo que hacía viable un segundo tenant desde el principio
(`tenants` sin unicidad de nombre, `internal_code` y `external_pms_id` únicos **por** tenant,
correos únicos en toda la instalación).

**API**: ninguna ruta nueva, ninguna modificada. `backend/openapi.json` no se mueve, así que
`api:check` no tiene nada que regenerar.

**Config/env**:

| Nombre | Dónde | Valor |
|---|---|---|
| `DEMO_ACCOUNT_PASSWORD` | `.env.example` (nombre, sin valor), `Settings`, `-e` de la invocación | La contraseña de las cuatro cuentas. Obligatoria, ≥ `PASSWORD_MIN_LENGTH`. |
| `autohostai-<env>-demo-account-password` | OCI Vault, declarado en Terraform | Su valor en el entorno remoto. |

**Constantes del árbol** (D2, publicables por diseño): `AutoHostAI Demo`,
`owner@demo.autohostai.test`, `manager@demo.autohostai.test`,
`cleaner@demo.autohostai.test`, `technician@demo.autohostai.test`.

**Fases del comando**, que es el contrato que R3.4 y R5.5 nombran:

```
configuration → refusal → bootstrap ──┐ (transacción propia; no-op en un reset)
                                      │
              ┌───────────────────────┘
              ▼
    ┌── delete ── converge ── seed ──┐   UNA transacción (D7)
    └────────────────────────────────┘
              │  commit
              ▼
        storage-sweep  (fuera de la transacción, D16)
              │
              ▼
        clear-lock     (Redis, fuera de la transacción, D9.5)
```

**Eventos**: los que ya emite cada caso de uso. Lo nuevo que aparecerá en el timeline de la
demo es `GUEST_MESSAGE_RECEIVED` y lo que la rama de escalado o de respuesta escriba, más la fila
de `AuditLog` `GUEST_ACCESS_TOKEN_ISSUED` del token de portal y las cuatro
`USER_PASSWORD_RESET` de la convergencia.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| `ignore_changes = [secret_content]` no se comporta como se espera en el provider de OCI, y cada `terraform apply` devuelve la contraseña al valor generado. Con R2.2, el siguiente reset la propaga a las cuatro cuentas y las credenciales publicadas dejan de funcionar **en silencio**. | Verificarlo en el primer `plan`/`apply` del change, y **antes de publicar las credenciales a nadie**: un `plan` que proponga volver a escribir `secret_content` teniendo ya el valor out-of-band puesto es la señal, y es visible. Si no aguanta, la salida es no depender de `ignore_changes`: la contraseña publicada pasa a ser la que genera `random_password`, leída del Vault, y la rotación es `terraform apply -replace`. Esto es lo que más cerca está de reabrir OQ2, así que se decide con el `plan` delante y no antes. |
| El workspace del runner es compartido entre workflows del repo y el `.env` no está versionado: un checkout con `clean: true` lo borraría y dejaría el deploy siguiente sin `.env` hasta que se re-renderice. | `clean: false` (D13) y precondición explícita que falla en rojo nombrando la fase. La deuda real —extraer el «Render .env» a un script versionado compartido— queda nombrada aquí y no se paga en este change. |
| El checkout del reset puede dejar el workspace en un `main` más nuevo que la imagen desplegada: `docker-compose.deploy.yml` nuevo con un `.env` viejo. Si el compose nuevo estrena un `${VAR:?}` que el `.env` no tiene, el reset falla. | Falla en rojo nombrando la fase, que es el comportamiento correcto; el deploy siguiente lo arregla solo. Se acepta. |
| `schedule:` se desactiva tras 60 días sin actividad en el repo, la hora no es exacta y con el runner caído el job espera en cola. | Documentado en `docs/demo-tenant.md`; `workflow_dispatch` es la salida manual (R5.1). |
| El borrado deriva su orden de la metadata: una tabla nueva con una clave ajena que el orden topológico no resuelva (ciclo) rompería el reset **en el entorno público**. | El test de cobertura de D4 obliga a una decisión explícita por tabla; un ciclo lo detecta `sorted_tables` y el test cae en CI, no en la VM. |
| **Un visitante puede desactivar el reset para siempre, y es un límite aceptado y no un descuido.** La contraseña del `TENANT_OWNER` de la demo se publica a propósito, y ese rol tiene `MANAGE_TENANT_SETTINGS`: `PATCH /tenants/{id}` acepta `billing_email` y `name`. Cambiar `billing_email` hace que el guardián de identidad del comando —que es justo lo que impide adoptar un tenant ajeno que sólo comparte el nombre— refuse en todas las ejecuciones siguientes (código 1, «nada escrito»), así que el tenant **deja de resetearse**: lo que los visitantes hayan metido, PII de huésped incluida, sobrevive al borrado nocturno en vez de morir en 24 h. Cambiar `name` rompe además el `scalar_one_or_none()` de `bootstrap.apply_plan` con `MultipleResultsFound` en el despliegue siguiente. | **Decidido por el usuario en el gate de la sección 2 de `/sdd:run` (2026-08-23): se acepta y se documenta**, en vez de identificar el tenant por su clave primaria y converger `name`/`billing_email` en cada ejecución — que es la alternativa fuerte, y la que se descartó por lo que costaba: un quinto constante `DEMO_TENANT_ID` (enmienda a D2) y mover la creación de la fila de `bootstrap.apply_plan` a este comando (enmienda a D7). La mitigación es por tanto **operativa y no de código**: `docs/demo-tenant.md` (tarea 10.1) documenta el síntoma —el reset programado en rojo o el tenant sin refrescarse— y el arreglo a mano, que es devolver `billing_email` a `billing@demo.autohostai.test`. Nótese la dirección del fallo: **cierra**, no abre. Refusar es lo correcto ante un tenant que no se puede identificar; lo que se acepta es que un visitante pueda provocar ese refuse. La otra mitad de la contención sigue en pie: el aislamiento por tenant, que es lo que impide que esto alcance a `AutoHostAI Dev`. |
| Cuatro cuentas con contraseña publicada en un entorno alcanzable son cuatro cuentas que cualquiera puede usar para agotar recursos del tenant de demostración (subir fotos, abrir incidencias). | El límite es el declarado por el proposal: aislamiento por tenant, y `saas-cross-tenant` cerrada. El reset diario es también la contención: lo que un visitante acumule vive menos de 24 h. No se añade ninguna cuota, y consta como límite aceptado. |
| `MockAIAdapter.generate_response` lanza `KeyError` a propósito para tres intents; un mensaje sembrado que caiga en uno de ellos por la rama equivocada rompe el seed. | Los textos son constantes elegidas y pineadas por test contra el intent que deben producir, igual que `seed_demo` ya pinea la categoría y la severidad que el clasificador de incidencias debe dar. |

## Roadmap candidates found on the way

Neither belongs to this change, and both are written here so `/sdd:archive` can turn them into
roadmap entries instead of leaving them in a session transcript:

- **`tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature`
  is time-sensitive and flakes under host contention.** It asserts the `Cache-Control` max-age
  equals the remaining life of the signature, and on a loaded run it failed by 6 seconds
  (`abs(3600 - 3594)`); it passes 14/14 in isolation. Seen on 2026-08-23 during a full-suite run
  that took 19 minutes instead of 5 because four review agents were driving the same stack.
  Nothing in `demo-user` touches `maintenance/`. The fix is to compare against a bound rather
  than an equality, and it is somebody else's change to make.
- **The demonstration tenant's `audit_logs` grow without limit.** Named in D4bis point 3: the
  reset preserves them by R3.6, so the one table of a nightly-reset tenant that never shrinks is
  its audit trail, and every row's polymorphic `entity_id` dangles after the first reset. A
  retention rule for demo-tenant audit rows is the obvious follow-up and is deliberately not in
  this change.

## Open questions

Ninguna abierta. Las cuatro que este diseño levantó se resolvieron en el gate de `/sdd:design`
del **2026-08-23**, y cada una vive ya donde manda:

| # | Qué se preguntó | Resolución | Dónde vive |
|---|---|---|---|
| OQ1 | R4.3 obliga a publicar el enlace de portal y R2.5 prohíbe emitir cualquier token | Se imprime; R2.5 gana una excepción nombrada y acotada | **D19**, y la excepción bajada a `proposal.md` R2.5 |
| OQ2 | ¿Contraseña generada por Terraform o elegida? | Elegida, memorable y puesta out-of-band en el Vault; el valor concreto no se escribe en el repositorio | **D12** |
| OQ3 | ¿Se aprueba dejar `auth-tenancy.md` sin modificar? | Sí | **D8**, y la lista de *Affected specs* del `proposal.md` corregida |
| OQ4 | Cadencia | Diaria, 03:15 UTC | **D20** |

Las dos enmiendas al `proposal.md` —la excepción de R2.5 y la lista de *Affected specs*— se
escribieron en ese mismo gate y no quedan pendientes: una enmienda que se queda en el design
acaba como un `SHALL` falso en la spec viva.
