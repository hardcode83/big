# Tasks: rule11-ownership-single-source

Orden de las secciones: primero el guard ejecutable (§1), porque las dos copias de
`cleaning` (§2) y cuatro docstrings del barrido lo citan y no se puede citar lo que no
existe; después la autoridad (§3), porque el barrido (§4) sustituye atribución por citas a
una tabla que ya tiene que estar completa; el guardián (§5) va al final porque su eje de
sumidero se alimenta de esa tabla y su verde solo significa algo sobre un árbol ya barrido.

El sistema queda en verde al cerrar cada sección. Dentro de §1 **no**: la tarea 1.2 rompe
tests y la 1.4 los clasifica, y por eso están en la misma sección (Riesgos del design,
punto R6.4).

> **Nota de `/sdd:review` (2026-08-18).** Donde este documento dice «las cuatro lecturas no
> scoped» (1.2, 1.5, 4.9) son **cinco**: el panel encontró `find_by_token_hash`
> (`app/integrations/infrastructure/repositories.py`) fuera del censo. El texto de las tareas se
> deja como se aprobó —es el registro de lo que se planificó— y la corrección vive en la enmienda
> de D9, que es la que gobierna. La quinta está guardada, declarada y con su test de R6.3.

## 1. El invariante «sesión sin marcar» pasa a código <!-- panel: PASS 2026-08-17 -->

<!--
Panel (arquitectura, seguridad, QA, tenancy, documentación; se omitieron i18n y cicd por no
haber cadenas de UI ni workflows/Terraform en el diff). Rondas: 2.
- Arquitectura PASS sin hallazgos. Tenancy PASS sin hallazgos. QA PASS: verificó con mutación
  que el censo enrojece al añadir un quinto llamante y al quitar una llamada, y que los cuatro
  tests de R6.3 detectan la regresión.
- Seguridad: 3 hallazgos. (1) la aserción que sustituí observaba la fixture y no la app —
  arreglado grabando el marcador dentro de la petición (`bound_tenants`), y su re-review
  demostró por mutación que esa aserción es la ÚNICA que caza un binder anulado en la raíz de
  composición; (2) el censo se evadía con `db.require_unmarked_session(...)` — `_calls_the_guard`
  ahora casa `ast.Attribute`; (3) el docstring de `cleaning` deriva la precondición de la forma
  de la ruta — DIFERIDO a la tarea 2.1, que es quien gobierna ese texto (R5.1/R5.2), con la
  redacción acordada con el revisor.
- Documentación: 4 referencias colgantes al docstring que este change vació
  (`auth/domain/ports.py` x3, `cli/bootstrap.py`), todas repuntadas a
  `require_unmarked_session` + `tests/test_unscoped_reads.py`. Barrido final del literal: limpio.
-->


- [x] 1.1 `TenantMarkedSessionError(RuntimeError)` en `backend/app/core/tenancy.py` (junto a
  `CrossTenantWriteError`, misma familia: error de programación, sale como 500, nunca se
  captura) y `require_unmarked_session(session: AsyncSession, *, read: str) -> None` en
  `backend/app/core/db.py`, junto a `bind_session_to_tenant` y al listener — vive ahí porque
  `backend/tests/test_session_marking.py:67` prohíbe tocar `session.info` en cualquier
  módulo de `app/` que no sea `core/db.py`. Test unitario nuevo en
  `backend/tests/test_session_marking.py` (o fichero propio junto a él): sesión sin marcar
  pasa; sesión marcada lanza `TenantMarkedSessionError` con el nombre de la lectura y la
  precondición en el mensaje. [R6.1, R6.2]
- [x] 1.2 Invocar el guard como **primera sentencia** del cuerpo de las cuatro lecturas no
  scoped, y recortar el docstring de cada una a una cita del guard y del límite 2 de
  `_scope_statement_to_tenant` — sin reproducir enumeración ni recuento:
  `find_by_email_globally` y `consume_globally`
  (`backend/app/auth/infrastructure/repositories.py`), `find_live_by_token_hash`
  (`backend/app/guests/infrastructure/portal_repositories.py`),
  `locate_without_tenant_scoping`
  (`backend/app/cleaning/infrastructure/repositories.py`). Se conservan los párrafos que
  enuncian la creencia falsa **para refutarla** (R2.4). [R6.1, R6.5]
- [x] 1.3 Un test por lectura que la invoque sobre una sesión **ya marcada** y exija
  `pytest.raises(TenantMarkedSessionError)`. No puede apoyarse en observar filas: sobre
  sesión marcada el listener filtra hasta el `select` de una columna y el caso sería
  indistinguible de un resultado vacío legítimo. Ficheros: junto a los tests de cada
  adaptador (`backend/tests/auth/`, `backend/tests/guests/`, `backend/tests/cleaning/`).
  [R6.3]
- [x] 1.4 Correr la suite completa (`docker compose exec backend uv run pytest`) y
  clasificar **cada** rojo. **Resultado medido: 44 rojos, y ninguno cae en las dos clases que
  esta tarea preveía** — ni «afirmaba el filtrado silencioso» ni «caller legítimo roto». Los 44
  afirman comportamiento ordinario y caen por la sesión compartida de las fixtures
  (`backend/tests/conftest.py`, una sola `db_session` por test frente a una por petición en
  producción). Desviación llevada al gate y aprobada por Jose; enmienda escrita en D13.
  Arreglo: `request_session_override` borra el marcador de tenant al terminar cada petición,
  en cuatro fixtures (raíz, `cleaning/conftest.py`, las dos de `test_portal_api.py`), más un
  envoltorio local de `apply_plan` en `test_seed_demo.py` porque cada `make seed-demo` es un
  proceso nuevo. **Ninguna aserción tocada**; dos comentarios de `test_portal_api.py`
  actualizados porque describían la sesión compartida. Las dos secuencias que tenían que
  seguir pasando lo hacen (`app/cli/seed_demo.py` y `GuestPortalAuthenticator`), y los cuatro
  candidatos que el design localizó (`test_tenant_filter.py`, `test_isolation.py`,
  `test_route_authorization.py` y — salvo por la sesión compartida — `test_recovery_api.py`)
  nunca estuvieron rojos por su propia causa. **No** se abre entrada en `BLOCKED.md`: el
  arreglo de fondo sigue en el roadmap como `test-session-per-request` (D13), y las dos formas
  fieles se midieron para justificarlo (249 y 40 rojos respectivamente). [R6.4]
- [x] 1.5 `backend/tests/test_unscoped_reads.py`: test estático que afirma que el conjunto
  de `(módulo, función)` que invocan `require_unmarked_session` en `app/` es **exactamente**
  las cuatro lecturas declaradas — añadir un llamante sin declararlo es rojo, quitar una
  llamada es rojo. El propio test escribe su residual: no detecta una **quinta** lectura no
  scoped nueva que ni llame al guard ni se declare, y la convención `*_globally` ya está
  declarada no exhaustiva por dos specs. [R6.1, R6.3, D9]
- [x] 1.6 El párrafo del **límite 2** del docstring de `_scope_statement_to_tenant`
  (`backend/app/core/db.py`) remite a `require_unmarked_session` como el sitio donde el
  invariante pasa a vivir, sin reproducir el censo de quién marca la sesión. [R6.5, D8]

## 2. Las dos copias de `cleaning` dejan de afirmar el atajo refutado <!-- panel: PASS 2026-08-17 -->

<!--
Panel (seguridad, tenancy, documentación; sección de sólo prosa, sin arquitectura ni QA).
Rondas: 2. Documentación PASS a la primera.
- Tenancy: mi reescritura nombraba `SessionTenantBinder` como contraejemplo, reproduciendo un
  fragmento del censo que R5.2 prohíbe — el hecho pasaba a vivir en tres sitios. Arreglado:
  ambos docstrings remiten al límite 2 «que nombra los casos» sin repetirlos.
- Seguridad: (1) TERCERA copia, en el contrato del puerto
  (`cleaning/domain/repositories.py:322`), que derivaba la precondición de que la ruta sea
  anónima y citaba el límite 2 como si lo respaldara — arreglada; (2) «checked» prometía una
  verificación inexistente — ahora consta como lectura humana fechada, y que ningún test lo
  afirma. En la re-review retiró su aceptación del contraejemplo nombrado y respaldó el arreglo
  de tenancy: el guard degradó la refutación de única protección a mera explicación.
- Los dos ejes convergieron sin que yo arbitrara. Barrido final de paráfrasis (tenancy): ningún
  otro sitio de `backend/app` deriva «sin marcar» de «ruta anónima».
-->


- [x] 2.1 Eliminar «the only place that marks» de
  `backend/app/cleaning/api/dependencies.py:298` y de
  `backend/app/cleaning/infrastructure/repositories.py:534`, y sustituirla por la
  precondición que de verdad se cumple —la sesión de esa ruta no se marca nunca, porque el
  endpoint no declara `require(...)`— más una cita al límite 2 y al guard de 1.1. Sin
  enumerar quién sí marca (`get_authenticated_request`, `SessionTenantBinder`, cada CLI):
  esa es la lista que R2.4 declara imposible de mantener. **Tercer sitio, encontrado por el
  panel de seguridad y no por la lista de esta tarea**: el contrato del puerto en
  `backend/app/cleaning/domain/repositories.py:322` derivaba la precondición de que la ruta
  sea anónima y **citaba el límite 2 como si lo respaldara**, cuando dice lo contrario — y la
  parafraseaba, así que el `grep` de 2.2 no podía verlo. Es el sitio que más importa: es lo
  que lee quien implemente el puerto. Mismo tratamiento que los otros dos. Consecuencia, igual
  que D2 para R1.2: la lista de R5.1 es un suelo verificado, no un techo, y el verde de 2.2 no
  prueba que el barrido esté completo porque su literal no alcanza a las paráfrasis.
  [R5.1, R5.2]
- [x] 2.2 Comprobar que
  `grep -rn "only place that marks\|only thing that marks" backend/app` devuelve
  **únicamente** `backend/app/auth/infrastructure/repositories.py:120`, que lo enuncia para
  refutarlo. [R5.3, R2.4]

## 3. La tabla de la regla 11 queda completa (autoridad) <!-- panel: PASS 2026-08-17 -->

<!--
Panel (seguridad, documentación; sección de sólo steering). Rondas: 2.
- Seguridad: (1) la fila de `audit_logs.changes` prometía una garantía por construcción más
  fuerte que el mecanismo — `AuditLog` es un dataclass mutable y `SqlAlchemyAuditLogRepository
  .add` copia `changes` sin validar, mientras revalida `actor_guest_token_hash` por ese mismo
  motivo. Añadida la cláusula «lo que esto no cierra», como en `messages.content`; (2) el
  recuento «los cinco escritores vivos» no cuadraba con nada; (3) la fila (b) decía «los avisos
  de asignación», dejando fuera `owner_approval_notification` y `no_cleaner_available_notification`
  — ahora nombra el hogar del contrato, no el tipo de aviso.
- Documentación: el mismo recuento, encontrado por su cuenta.
- Los dos volvieron a cazar el numeral en la segunda ronda: mi «siete sitios» eran ocho. En vez
  de corregirlo a ocho —que es lo que ambos proponían— se quitó la cifra y se dejó el método,
  que es lo único que no se queda obsoleto. El párrafo ya se había equivocado dos veces.
- R4.6 verificado por seguridad: los cuatro párrafos de excepción quedan byte-idénticos, la
  excepción 1 se recorta (sin escritor) y no se deriva ningún contrato nuevo.
-->

- [x] 3.1 En `sdd/steering/security.md`, la fila de `audit_logs.changes` responde «quién la
  escribe» con **`AuditLogFactory.build` + `ChangeSet`** —el punto único de paso— y dice la
  consecuencia explícitamente: cualquier módulo puede escribir esa columna y ninguno puede
  derivar un contrato propio, porque `ChangeSet` rechaza por construcción todo campo fuera
  de `AUDITABLE_FIELDS` y la forma para un campo sensible es `{"changed": true}`. **No** se
  enumeran los doce llamantes. [R4.1, R4.2]
- [x] 3.2 Antes de tocar la fila de `notification_logs.subject`/`body`, comprobar en el
  código a qué contrato se atiene cada escritor omitido:
  `app/maintenance/domain/notifications.py:79,120`,
  `app/cleaning/domain/notifications.py:51,91` y
  `app/guests/application/use_cases.py:595`. Si los dos primeros se atienen al contrato que
  ya hay, entran como **una sola entrada por contrato** (no una por módulo); el tercero no
  es hueco (es el código de `access-notifications`, ya atribuido). Si alguno **no** se
  atiene, abrirle fila propia con su forma y no ensanchar la excepción 1 por parecido.
  [R4.3, R4.4]
- [x] 3.3 Partir esa fila en dos en `sdd/steering/security.md`: **(a)** la excepción 1 (el
  `****XX` de un código de acceso), licencia concedida **sin escritor vivo** —consta que
  nadie la ejerce todavía, no se borra—; **(b)** «estructurada, forma cerrada: constante más
  identificadores», con los escritores vivos (`celery-jobs`, `access-notifications`,
  `auth-account-recovery`, `messaging-ai` y la entrada de 3.2), sosteniéndose por
  **disciplina del llamante** —no hay punto único de paso—, igual que la tabla ya dice del
  tercer escritor de `incidents.title`. [R4.3, R4.6]
- [x] 3.4 Cerrar en la prosa de `sdd/steering/security.md` el hueco que ella misma declara
  (línea ~124) y verificar que el diff **no deriva ningún contrato nuevo ni ensancha
  ninguna excepción**: este change declara propiedad, no concede nada. [R4.6]

## 4. Barrido: la propiedad desaparece de los diecinueve sitios <!-- panel: PASS 2026-08-17 -->

<!--
Panel (documentación PASS sin hallazgos; seguridad en versión acotada tras dos intentos que
se colgaron en el watchdog — queda dicho por honestidad, no fue una revisión amplia).
- Seguridad, 1 hallazgo aplicado: el barrido borró de `WebhookEventModel` la única mención de
  `scrub_card_data`, que R2.2 nombra explícitamente como mecanismo a conservar, dejando la
  frase «what `payload` just dropped» apuntando a un mecanismo que ya no explicaba nadie.
  Restaurado como mecanismo (hecho sobre este módulo), no como atribución.
- Verificó además que la afirmación nueva de la migración es cierta: nada escribió en
  `webhook_events` entre `domain-foundation-financial` y `reservations-webhooks`
  (`git log -S "WebhookEventModel"`, dos changes; sin escritor en `app/cli/`).
- Los sitios 20-25 no los encontró este panel sino el guardián de §5 y su revisor: ver la nota
  de esa sección. Diecinueve era el suelo.
-->

Cada sitio conserva (a) que la columna es un sumidero de texto en claro, (b) que su
contrato es la regla 11 de `steering/security.md` con enlace, (c) el razonamiento **local**
de por qué esa columna es peligrosa ahí, y (d) el mecanismo que impone el contrato por
construcción cuando vive ahí. Se elimina exclusivamente **quién escribe y quién heredará**.
Las tres afirmaciones falsas se **borran**, no se corrigen.

- [x] 4.1 Modelos ORM: `backend/app/notifications/infrastructure/models.py`
  (`NotificationLogModel:28` — borrar «`last_error` still has no writer;
  `access-notifications` inherits that one…», que es falso desde 2026-08-08),
  `backend/app/audit/infrastructure/models.py` (`AuditLogModel:22` — borrar «Nothing writes
  here yet; `user-management` … inherit the contract», falso con doce llamantes hoy) y
  `backend/app/integrations/infrastructure/models.py` (`WebhookEventModel`). Conservar
  `ChangeSet`, `AuditLogFactory`, `WebhookEventFailure`, `scrub_card_data`, el enum de
  `DeliveryResult`, el índice de `audit_logs`, la ruta del código de acceso de PRD §17 por
  `body` y el `payload` verbatim de PRD §7.26. [R1.1, R1.2, R1.5, R2.1, R2.2]
- [x] 4.2 En el mismo fichero, `WebhookEventModel:51` deja de decir «el más expuesto de
  **las seis**» y dice «de las del censo», sin cifra: la cifra la gobierna la tabla, no este
  docstring. [R4.5, D11]
- [x] 4.3 Las tres copias de dominio que R1.2 no lista, encontradas aplicando R1.1:
  `backend/app/audit/domain/value_objects.py:5` («…and this change is its first writer»),
  `backend/app/cleaning/domain/notifications.py:5` («…fixed by `celery-jobs` (the first
  writer)») y `backend/app/notifications/domain/results.py:6` («This change is its first
  writer, so the contract is inherited here»). Quitar la atribución, conservar el mecanismo
  estructural. [R1.1, D2]
- [x] 4.4 `backend/alembic/versions/a4d17e83b6c1_reservations_webhooks.py:7-8`: la
  justificación de seguridad **afirma el hecho** —la tabla estaba vacía en todos los
  entornos cuando esta migración se aplicó, que es lo que la hacía segura— en vez de citar
  el docstring que 4.1 elimina. [R1.1, R1.2, D2]
- [x] 4.5 `sdd/specs/domain-foundation-financial.md:49-52`: pierde «**Siete** columnas»
  (son dieciséis), «una **única** excepción» (son cuatro desde `messaging-ai`) y «los tres
  docstrings la citan sin repetirla» (los tres la repiten). Queda con lo local: las columnas
  que **esta capacidad** introduce son sumideros y su contrato es la regla 11. [R1.2, R1.5,
  R4.5, D11]
- [x] 4.6 Las specs que declaran «primer escritor» de una columna del censo pasan a citar la
  tabla sin reproducir la atribución: `sdd/specs/user-management.md:11`,
  `sdd/specs/cleaning.md:265`, `sdd/specs/access-notifications.md` (líneas 207, 217 y 255),
  `sdd/specs/reservations-webhooks.md:218`, `sdd/specs/messaging-ai.md:94` (la copia número
  ocho, que cita la autoridad y reafirma la propiedad en la misma frase). La línea 217
  (`GUEST_ESCALATION` ganó su primer escritor el 2026-08-16) está **dentro** de alcance
  aunque nombre un miembro de enum: la tabla ya atribuye ese aviso a `messaging-ai`, así que
  es la misma propiedad declarada dos veces. [R1.1, R1.2, R1.3]
- [x] 4.7 `sdd/roadmap/user-management.md` y `sdd/roadmap/access-notifications.md`: quitar
  la atribución de sumidero, conservar el resto intacto. [R1.2]
- [x] 4.8 `sdd/specs/access-notifications.md:538`: «Valores de enum **sin escritor**» →
  «valores de enum que nadie escribe todavía». Los enums siguen fuera de alcance; esto es
  solo el residuo literal de la comprobación de R1.4. [R1.4, D6b]
- [x] 4.9 Repuntar al guard las cuatro specs que hoy señalan el docstring de
  `find_by_email_globally` como «el único sitio» donde vive la enumeración:
  `sdd/specs/auth-tenancy.md:45`, `sdd/specs/auth-account-recovery.md:329`,
  `sdd/specs/guest-portal-api.md:354`, `sdd/specs/seed-data-demo.md:538`. Y documentar en
  `sdd/specs/cleaning.md` su lectura no scoped (`locate_without_tenant_scoping`), hoy
  ausente de la spec — es la que nunca entró en el recuento «ONE OF THE THREE». [R6.5, D9]
- [x] 4.10 Comprobaciones de cierre del barrido: `sdd/specs/domain-foundation-core.md:31`
  (`wifi_password_encrypted`, `document_number_encrypted`) queda **intacto** —habla de
  cifrado en reposo, regla 3, y la tabla de la regla 11 no lo gobierna—; y
  `grep -rn "sin escritor\|Nothing writes here yet"` sobre el árbol de trabajo devuelve
  únicamente `sdd/steering/security.md`, `sdd/changes/` y
  `sdd/roadmap/rule11-ownership-single-source.md:3` (la nota de este change, que enuncia la
  patología para refutarla y queda con excepción declarada). **Verificado**: `git diff` de
  `domain-foundation-core.md` vacío, y el grep de R1.4 devuelve exactamente esos tres orígenes.
  **Dos sitios quedan en gris a propósito, para que los dirima el guardián de §5 y no yo**:
  `backend/app/audit/domain/actions.py:206` («first writer of `incidents`») y
  `backend/app/maintenance/infrastructure/repositories.py:329` («the first writer
  `owner_approvals` has ever had») atribuyen una **tabla** cuyas columnas sí están en el censo.
  Si sus bloques cruzan los dos ejes, el test los reclama y se barren; si no, no eran del censo.
  Ese es justo el orden que la cabecera de este documento declara. [R1.4, R2.3, R2.4, D6b]

## 5. El guardián que impide la copia número nueve <!-- panel: PASS 2026-08-17 -->

<!--
Dos cosas que sólo se supieron construyéndolo, y que quedan aquí porque cambian el resultado:

1. **El guardián se validó contra el árbol PRE-barrido**, no sólo contra el actual. Un guardián
   verde sobre un árbol ya limpio no demuestra nada; corriendo su detector sobre
   `git show HEAD:<fichero>` de los trece sitios barridos, la primera versión cazaba **diez de
   trece**. Los tres que se le escapaban nombraban la **tabla** y no la columna
   («primer escritor real de `audit_logs`», «las tres de `webhook_events` ya tienen escritor
   vivo») o usaban «is the writer», que no estaba en el vocabulario. Con los nombres de tabla y
   esas frases añadidos: **doce de trece**.

   **Corrección de `/sdd:review` (2026-08-18).** Esta nota dijo primero «trece de trece», y el
   panel de QA lo midió de nuevo: son **doce**. El que falta es
   `git show HEAD:sdd/specs/cleaning.md` («Este es el primer escritor de
   `CLEANING_TASK_ASSIGNED`»), que dispara el eje de propiedad pero **ningún** término del eje de
   sumidero, porque `CLEANING_TASK_ASSIGNED` es un tipo de aviso y no una columna. Lo barrió la
   tarea 4.6 a mano, no el guardián. Importa porque **R1.3 pone justo esa clase de copia en
   alcance** («el criterio es qué hecho se duplica, no de qué tipo es el objeto que lo lleva»):
   el guardián no puede hacer cumplir ese criterio. Queda como residual 8 del propio test, con
   su caso fijado por aserción.
2. **Y entonces reclamó dos sitios que el barrido de §4 no había tocado** —
   `app/maintenance/infrastructure/repositories.py:329` («the first writer `owner_approvals` has
   ever had», que 4.10 había dejado en gris a propósito para que lo dirimiera él) y
   `app/messaging/domain/templates.py:173` («`maintenance` is the writer of `incidents.title`»).
   Barridos los dos. Son los sitios **20 y 21**: la lista de diecinueve del design era, como D2
   ya decía de R1.2, un suelo verificado y no un techo.

3. **Y el panel de seguridad encontró cuatro más, en `backend/tests/`**, que el barrido no
   recorría: `audit/test_change_set_property.py`, `maintenance/test_free_text_sink_contract.py`
   y dos en `notifications/test_escalate_slas.py`. Son las copias **22 a 25**. El guardián ahora
   recorre también `tests/`, con una excepción declarada para sí mismo —sus dos ejes SON el
   vocabulario, así que se reclamaría entero— y las cuatro quedaron barridas.
   Otros ocho hallazgos del mismo panel, todos aplicados: el centinela sólo validaba `sdd/` y
   admitía un `docs/` vacío por `is_dir()`; un fichero que `ast` no pudiera parsear se
   reportaba como limpio (ahora es un fallo); el motivo escrito de la exclusión de `docs/adr`
   afirmaba un hecho falso; la magnitud del carve-out de `sdd/changes/` (36 bloques, ~16 ya
   congelados en `archive/`) no constaba; el `assert` del recuento era el único sin mensaje;
   el docstring prometía un override por variable de entorno que no existe —y que no se añade,
   porque sería la forma de apuntar el barrido a un directorio vacío—; y las excepciones no
   caducaban, así que ahora un `DECLARED_EXCEPTIONS` que ya no reclama nada sale en rojo.
-->

- [x] 5.1 `docker-compose.yml`: añadir `./sdd:/workspace/sdd:ro` y `./docs:/workspace/docs:ro`
  al servicio `backend` (junto al bind-mount de `deploy-dev.yml` que ya existe ahí por el
  mismo motivo). `docker-compose.deploy.yml` no se toca: no corre la suite. Sin variable
  nueva en `.env.example` — el override de raíz es de test, como `PROVENANCE_WORKFLOW_PATH`,
  que tampoco está ahí. [R3.1, D7]
- [x] 5.2 `backend/tests/test_rule11_ownership.py`: resolución de raíz por el patrón ya en
  uso (`backend/tests/provenance/test_workflow_to_endpoint_wiring.py:41-50` — variable de
  entorno, luego `/workspace/…`, luego `Path(__file__).resolve().parents[3]/…`) **más un
  centinela fail-closed**: exige que `<raíz>/steering/security.md` exista, contenga la
  cabecera de la tabla de la regla 11 y que el barrido vea un mínimo de ficheros Markdown;
  si no, `pytest.fail` — nunca `skip`, que en `-rs` se lee como «no aplicaba». Sin el
  centinela un bind mount con origen ausente lo crea Docker como directorio vacío y el
  guardián pasaría en verde sobre cero ficheros. [R3.1, D7]
- [x] 5.3 En el mismo test, la detección: partir cada fichero en **bloques** (párrafo o
  viñeta en Markdown con sus continuaciones; docstring o tirada de comentarios contiguos en
  Python) y marcar el bloque que contenga a la vez algo de los **dos ejes** — eje sumidero
  (nombre de una de las dieciséis columnas del censo, o referencia a la regla 11: `regla 11`,
  `rule 11`, `sumidero de texto en claro`, `cleartext sink`, `censo`) y eje propiedad
  (`primer escritor`, `escritor vivo`, `first writer`, `writes here`, `sin escritor`,
  `Nothing writes here yet`, `hereda(rá) el contrato`, `inherit(s) the contract`, `quien la
  escribe`, `lo escribe X`). El bloque —y no la línea— porque la copia número ocho reparte
  cita y atribución entre `messaging-ai.md:93` y `:94`. Los dos ejes —y no uno— porque
  `primer escritor` sale diecinueve veces y la mayoría no son sumideros de la regla 11.
  [R3.1]
- [x] 5.4 Mensaje de fallo: fichero, línea del bloque y la frase encontrada, remitiendo a la
  tabla de `sdd/steering/security.md` como el sitio donde va. [R3.2]
- [x] 5.5 Exclusiones y honestidad del verde, en el propio test. Excluir `sdd/changes/`
  **entero** (no solo `archive/`: un registro de change es el mismo documento antes y
  después del `mv`, y excluir solo el destino haría que el guardián pasara de rojo a verde
  sin cambiar una palabra) y `docs/adr/` (inmutables por convención;
  `docs/adr/0007-webhook-event-retry-columns.md:43` es su único caso hoy). **No** excluir
  `sdd/specs/`, `sdd/roadmap/`, el resto de `sdd/steering/`, `docs/*.md`, `backend/app/` ni
  `backend/alembic/versions/`. Lista de excepciones con **motivo escrito en cada entrada**,
  arrancando con una sola: `sdd/roadmap/rule11-ownership-single-source.md`. Y la lista de lo
  que el guardián **no** detecta: atribución parafraseada, atribución repartida entre dos
  bloques, propiedad de una columna que aún no está en el censo, el hueco de
  `app/cli/seed_demo.py` frente al guardián de `maintenance` (`security.md:126`, fuera de
  alcance por decisión del proposal) y los ficheros excluidos. [R3.3, R3.4, D3, D6b]

## 6. Verification

- [x] 6.1 `make down && make up` **antes** de correr la suite: un contenedor `backend` ya
  levantado no ve los bind-mounts de 5.1, y el centinela de 5.2 fallaría — eso es el
  centinela funcionando, no un fallo del guardián.
- [x] 6.2 Suite completa del backend en verde: `docker compose exec backend uv run pytest`.
  Incluye los dos ficheros nuevos (`test_rule11_ownership.py`, `test_unscoped_reads.py`) y
  los reconvertidos en 1.4. No hay comando de lint ni de typecheck en este proyecto: la
  entrada `backend-static-typecheck` del roadmap es la que los traerá, y `sdd/project.md` no
  declara ninguno hoy.
- [x] 6.3 Los tres `grep` que los criterios exigen literalmente:
  `grep -rn "sin escritor\|Nothing writes here yet"` (solo `security.md`, `sdd/changes/` y
  la nota de roadmap de este change), `grep -rn "only place that marks\|only thing that
  marks" backend/app` (solo la línea que lo refuta) y
  `grep -rn "first writer\|primer escritor"` revisado sitio por sitio contra la lista de
  §4. [R1.4, R5.3]
- [x] 6.4 Cobertura de requisitos, comprobada a mano sobre el diff: R1 (§4), R2 (§4.1,
  §4.10), R3 (§5), R4 (§3, §4.2, §4.5), R5 (§2), R6 (§1). Y que el diff de
  `sdd/steering/security.md` **no** contiene ningún contrato nuevo ni excepción ampliada.
- [x] 6.5 Sin migración, sin endpoint, sin string de UI: `backend/openapi.json`,
  `frontend/lib/api/generated/openapi.d.ts`, `locales/` y `.env.example` quedan intactos —
  y que sigan intactos es parte de la verificación, porque el change es de propiedad de la
  información.
