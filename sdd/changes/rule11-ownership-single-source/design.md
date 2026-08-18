# Design: rule11-ownership-single-source

## Context

La autoridad de la regla 11 es la tabla de `sdd/steering/security.md:130-151` (dieciséis
columnas, veinte filas) y la prosa que la rodea. Fuera de ella, la **propiedad** de cada
sumidero está reafirmada en **al menos** diecinueve sitios verificados sobre este árbol —seis más
de los trece que enumera R1.2, y un suelo y no un techo, como razona D2: `/sdd:run` acabó
barriendo **veinticinco**, porque el guardián de §5 reclamó dos que este censo no vio
(`app/maintenance/infrastructure/repositories.py`, `app/messaging/domain/templates.py`) y el
panel de seguridad cuatro más en `backend/tests/`—, tres de los cuales afirman algo falso hoy
(`backend/app/audit/infrastructure/models.py:22`,
`backend/app/notifications/infrastructure/models.py:28`,
`sdd/specs/domain-foundation-financial.md:49-52`).

El segundo sumidero de la misma patología es el invariante «esta lectura tiene que correr
antes de que nadie marque la sesión con un tenant». Su hogar declarado es el docstring de
`SqlAlchemyUserRepository.find_by_email_globally`
(`backend/app/auth/infrastructure/repositories.py:98-162`), que cuatro specs citan como «la
enumeración vive en un solo sitio» — y que **hoy dice «ONE OF THE THREE» cuando son cuatro**:
`SqlAlchemyUnscopedCleaningPhotoLocationQuery.locate_without_tenant_scoping`
(`backend/app/cleaning/infrastructure/repositories.py:543`) nunca entró en la lista. Es la
tercera vez que ese recuento se queda obsoleto, y el propio docstring narra las dos
anteriores. El mecanismo que hace peligroso el descuido es el listener
`_scope_statement_to_tenant` (`backend/app/core/db.py:66`), que sobre una sesión marcada
**filtra en silencio** —hasta un `select` de columnas— en vez de fallar.

Dos hechos del entorno condicionan el diseño más que ninguna preferencia:

1. `backend/tests/test_session_marking.py:67-79` prohíbe **cualquier** acceso a
   `session.info` en `app/` fuera de `app/core/db.py`. Un guard que compruebe el marcador no
   puede vivir en los cuatro adaptadores.
2. `docker-compose.yml:97-103` monta **solo** `./backend:/app`. Un test de la suite del
   backend no ve `sdd/` ni `docs/` cuando corre en local. En CI sí los ve, porque
   `backend-tests.yml:327` corre `pytest` con `working-directory: backend` sobre el checkout
   completo. Ya hay precedente resuelto de esta asimetría:
   `backend/tests/provenance/test_workflow_to_endpoint_wiring.py:41-50`, con su bind-mount
   de solo lectura en `/workspace/`.

No hay diagrama: el change no introduce ni flujo, ni máquina de estados, ni interacción
nueva entre componentes. Lo que añade son dos guardianes y un barrido de prosa, y un dibujo
de eso no diría nada que no diga esta tabla de decisiones.

## Decisions

### D1 — Cada sitio conserva tres cosas y pierde una

**Elegido:** en cada uno de los diecinueve sitios se conserva (a) que la columna es un
sumidero de texto en claro, (b) que su contrato es la regla 11 de `steering/security.md`
—con enlace—, (c) el razonamiento **local** de por qué esa columna es peligrosa en ese
módulo, y (d) el mecanismo que impone el contrato por construcción cuando vive ahí
(`ChangeSet`, `AuditLogFactory`, `WebhookEventFailure`, `scrub_card_data`, el enum de
`DeliveryResult`). Se elimina exclusivamente **quién escribe y quién heredará**. Cubre R1.1,
R2.1 y R2.2.

Las tres afirmaciones falsas se **borran**, no se corrigen (R1.5): el objetivo declarado es
que no exista una novena versión que corregir, y una corrección crea una.

Rejected: dejar la atribución y añadir «ver la tabla, que manda» — la copia número ocho
(`sdd/specs/messaging-ai.md:94`) cita la autoridad y reafirma la propiedad en la misma frase,
que es la evidencia empírica de que remitir no impide la copia.

Rejected: quitar también la señal de sumidero — dejaría a quien lee `AuditLogModel` sin nada
que le mande a la autoridad, que es lo que R2 existe para prevenir.

### D2 — El censo de sitios lo fija R1.1; la lista de R1.2 es su suelo, no su techo

**Elegido:** el barrido cubre los trece sitios de R1.2 **más los seis que el barrido de esta
fase encontró aplicando R1.1**, porque R1.1 es la regla y R1.2 dice «estos sitios,
verificados sobre este árbol» — un mínimo verificado, no una enumeración cerrada. Los seis:

| Sitio | Qué afirma hoy |
|---|---|
| `backend/app/audit/domain/value_objects.py:5` | «`audit_logs.changes` is one of them, and this change is its first writer» |
| `backend/app/cleaning/domain/notifications.py:5` | «whose contract for `notification_logs.subject`/`body` was fixed by `celery-jobs` (the first writer)» |
| `backend/app/notifications/domain/results.py:6` | «This change is its first writer, so the contract is inherited here» |
| `sdd/specs/access-notifications.md:207` | «`auth-account-recovery` es el segundo escritor vivo de `notification_logs`» |
| `sdd/specs/domain-foundation-financial.md:49` | «**Siete** columnas del esquema son texto o JSON libre» (son dieciséis) |
| `backend/alembic/versions/a4d17e83b6c1_reservations_webhooks.py:7-8` | cita el docstring que D1 elimina («Nothing writes here yet») como prueba de que la tabla estaba vacía |

El de la migración se resuelve **sin perder información y sin citar un docstring que dejará
de existir**: la frase pasa a afirmar el hecho directamente —la tabla estaba vacía en todos
los entornos cuando esta migración se aplicó—, que es lo que hacía segura la migración.
Aditivo respecto a R1.2, cubierto por R1.1.

Rejected: limitarse a los trece — dejaría vivos tres sitios de código con la misma patología
y el guardián de D6 los reclamaría inmediatamente, con lo que el change no cerraría en verde.

### D3 — Los registros históricos quedan fuera, y son tres clases y no una

**Elegido** (amplía R3.3; resuelto en el gate de `/sdd:design`, aprobado por Jose): el barrido
y el guardián excluyen `sdd/changes/` **entero** (no solo `sdd/changes/archive/`) y
`docs/adr/`. Amplía la letra de R3.3 y sirve su intención.

Un registro de change es **el mismo documento antes y después** de que `/sdd:archive` lo
mueva: excluir `archive/` pero no su origen haría que el guardián pasara de rojo a verde por
un `mv`, sin que cambiara una palabra. Y los ADR son inmutables por convención —se
sustituyen, no se editan—, que es el mismo argumento por el que R3.3 excluye los archivos;
`docs/adr/0007-webhook-event-retry-columns.md:43` es su único caso hoy.

Lo que **no** se excluye: `sdd/specs/`, `sdd/roadmap/`, `sdd/steering/` (salvo
`security.md`), `docs/*.md` de capacidad, `backend/app/`, `backend/alembic/versions/`.
`sdd/roadmap/` es permanente —sobrevive al archivado, como demuestran los 55 ficheros de
`sdd/roadmap/`— y R1.2 ya pone dos de sus notas en alcance.

Rejected: excluir solo `archive/` — la incoherencia del `mv` de arriba.

Rejected: excluir `sdd/` entero y vigilar solo código — dejaría fuera nueve de las diecinueve
copias, que es donde vive la mayoría.

### D4 — `audit_logs.changes`: la fila declara el punto de paso, no los doce llamantes

**Elegido:** la fila responde «quién la escribe» con **`AuditLogFactory.build` + `ChangeSet`**
y dice la consecuencia explícitamente: cualquier módulo puede escribir esa columna y ninguno
puede derivar un contrato propio, porque `ChangeSet` rechaza por construcción todo campo
fuera de `AUDITABLE_FIELDS` y la forma para un campo sensible es `{"changed": true}`.
Verificado: dieciséis módulos nombran `AuditLogFactory`, doce de ellos como llamantes.
Cubre R4.1 y R4.2.

Rejected: enumerar los doce — es exactamente la lista que nadie actualiza, y la copia número
trece nacería con el siguiente módulo que audite algo (R4.1 lo prohíbe).

### D5 — `notification_logs.subject`/`body`: dos escritores omitidos y no tres, y comparten un solo contrato

**Elegido:** la fila gana **una** entrada, no tres, sobre la fila (b) que abre D5b. Comprobado
escritor por escritor (R4.3 obliga a comprobar a qué contrato se atiene cada uno antes de
declararlo):

| Módulo | `subject` | `body` | Contrato |
|---|---|---|---|
| `app/maintenance/domain/notifications.py:79,120` | constante | constante + 2-3 identificadores | el que ya hay |
| `app/cleaning/domain/notifications.py:51,91` | constante | constante + 2 identificadores | el que ya hay |
| `app/guests/application/use_cases.py:595` | constante | constante + 1 identificador | **ya está en la fila** |

El tercero **no es un hueco**: es el código de `access-notifications` —el aviso de
presentación legal fallida— que la fila ya atribuye a ese change. Vive en `guests/` porque
ahí vive la capacidad, no porque sea un escritor sin declarar. Así que los omitidos son dos,
`maintenance` y `cleaning`, y como los dos se atienen al contrato que ya hay, entran **como
una sola entrada por contrato** (R4.3) y no abren fila propia (R4.4 no se dispara).

Rejected: tres entradas, una por módulo — R4.3 manda declarar por contrato, y tres módulos
con el mismo contrato en tres entradas es la lista de módulos que R4.1 prohíbe.

Rejected: tratar `guests/` como cuarto escritor — sería declarar dos veces la misma
propiedad, que es la patología del change.

### D5b — La fila de `notification_logs.subject`/`body` se parte: la licencia por un lado, el contrato vivo por otro

**Elegido** (resuelto en el gate de `/sdd:design`, aprobado por Jose): dos filas donde hoy hay
una.

- **(a) excepción 1** — el `****XX` de un código de acceso, **sin escritor vivo**. Es la
  licencia que la regla concede y que hoy nadie toma; el caso que la motiva es la entrega del
  código de PRD §17, que no tiene escritor.
- **(b) estructurada, forma cerrada: constante más identificadores** — los escritores vivos:
  `celery-jobs` (escalados de SLA), `access-notifications` (aviso de presentación legal
  fallida), `auth-account-recovery` (constantes sin enlace), `messaging-ai`
  (`GUEST_ESCALATION`) y la entrada de D5 (`maintenance` + `cleaning`). La forma se sostiene
  por **disciplina del llamante**: no hay punto único de paso que la imponga, igual que ya dice
  la tabla del tercer escritor de `incidents.title`.

Lo que lo justifica es una verificación, no una preferencia: **ninguno de los cinco escritores
vivos ejerce la excepción 1**. `celery-jobs` escribe `subject="SLA breach"` y un cuerpo de
identificadores (`notifications/application/use_cases.py:234-249`); los otros cuatro, lo mismo.
La fila decía «Forma: excepción 1» para todos, atribuyéndoles una licencia que ninguno toma.

**No concede nada** (R4.6): recorta una licencia en vez de ampliarla, y quien necesite el
código enmascarado va a (a) y es su primer escritor, con la puerta que la tabla ya sabe
describir. Es el mismo movimiento con el que `incidents.title` se partió en `messaging-ai` y
otra vez en `seed-data-demo-extension`.

Y es lo que hace que la fila **deje de podrirse**, que es el objetivo de R4: un aviso nuevo con
esa forma entra en (b) sin declarar nada, porque (b) declara un contrato y no una lista de
changes.

Rejected: una sola fila con los cinco bajo la etiqueta de excepción 1 — la primera columna del
censo seguiría afirmando algo que sus propios escritores no hacen, y la fila volvería a
necesitar una entrada por cada aviso nuevo.

Rejected: borrar la excepción 1 por no tener escritor — sería un cambio de contrato, que R4.6
prohíbe; la licencia sigue concedida, simplemente consta que nadie la ejerce todavía.

### D6 — El guardián detecta por bloque y en dos ejes, con lista de excepciones razonada

**Elegido:** un test que recorre el árbol, lo parte en **bloques** y marca un bloque que
contenga a la vez algo de los dos ejes:

- **Eje sumidero**: el nombre de una de las dieciséis columnas del censo
  (`notification_logs.subject`, `audit_logs.changes`, …) **o** una referencia a la regla 11
  (`regla 11`, `rule 11`, `sumidero de texto en claro`, `cleartext sink`, `censo`).
- **Eje propiedad**: `primer escritor`, `escritor vivo`, `first writer`, `writes here`,
  `sin escritor`, `Nothing writes here yet`, `hereda(rá) el contrato`,
  `inherit(s) the contract`, `quien la escribe`, `lo escribe X`.

El **bloque y no la línea** es la decisión de fondo: la copia número ocho reparte la cita a
la autoridad y la atribución entre `sdd/specs/messaging-ai.md:93` y `:94`, así que un
guardián por línea no la ve. Un bloque es un párrafo o viñeta en Markdown (separado por
línea en blanco, con las viñetas de continuación pegadas a la suya) y un docstring o una
tirada de comentarios contiguos en Python.

Los **dos ejes** son lo que hace que el guardián signifique algo: `primer escritor` sale
diecinueve veces en el árbol y **la mayoría no son sumideros de la regla 11**
(`conversations`, `owner_approvals` la tabla, `reservations.guest_id`,
`current_operational_state`, `wifi_password_encrypted`). Un eje solo reportaría veinte
sitios y su lista de excepciones tendría que nombrarlos todos, que es lo que
`test_free_text_sink_contract.py` documenta como prueba de nada.

Cuando falla, nombra fichero, línea del bloque y la frase encontrada, y remite a la tabla
(R3.2). La lista de excepciones lleva **el motivo escrito en cada entrada**, como hace
`test_free_text_sink_contract.py:219-244`; una entrada sin motivo es un `assert` que se
puede ampliar sin que nadie lo note.

**La lista arranca con una sola entrada**, decidida en el gate (ver D6b):
`sdd/roadmap/rule11-ownership-single-source.md`, la nota de este propio change, que enuncia la
patología y cita el `grep` para poder cerrarla. R2.4 conserva lo que enuncia la creencia **para
refutarla**, y esta nota es el único sitio donde consta que el criterio se pidió.

**Lo que el guardián NO detecta, dicho en el propio test** (R3.4), y no es una lista de
buenos deseos: cada punto es una forma que existe hoy en el árbol o que tumbó una versión
anterior de un guardián hermano.

1. Una atribución **parafraseada** sin ninguna de las frases del eje de propiedad («esta
   capability estrena la columna», «desde aquí se rellena»). El eje es un vocabulario, no un
   analizador de significado.
2. Una atribución **repartida entre dos bloques** —la columna en un párrafo, el dueño en el
   siguiente—. El bloque cierra el caso de dos líneas contiguas, no el de dos párrafos.
3. Un sitio que declara propiedad de una columna que **aún no está en el censo**: el eje de
   sumidero se alimenta de la tabla, así que la columna número diecisiete es invisible hasta
   que entra en ella. Es la misma ceguera que `webhook_events.event_type` tuvo durante dos
   changes.
4. El hueco que el propio steering documenta sobre `app/cli/seed_demo.py` y el guardián de
   `maintenance` (`security.md:126`): queda **fuera de alcance** por decisión del proposal, y
   el test lo dice en vez de dejar que su verde se lea como cobertura.
5. Los **ficheros excluidos por D3**. Una copia dentro de un registro de change, de un
   archivo o de un ADR no se reporta, a propósito.

Rejected: un analizador AST sobre docstrings — resuelve el lado Python y no toca los nueve
sitios de Markdown, que son la mayoría.

Rejected: un solo eje (la frase de propiedad) — veinte falsos positivos, ninguno accionable.

Rejected: comparar contra la tabla y exigir coincidencia — obligaría a mantener una segunda
copia estructurada de la tabla, que es la patología con otro formato.

### D6b — La comprobación literal de R1.4 sobrevive con una excepción declarada

**Elegido** (resuelto en el gate de `/sdd:design`, aprobado por Jose): tras el barrido de
D1-D2, `grep -rn "sin escritor\|Nothing writes here yet"` deja tres líneas fuera de
`sdd/steering/security.md` y `sdd/changes/archive/`, y se resuelven así:

1. `backend/alembic/.../a4d17e83b6c1:8` — la resuelve D2: la frase afirma el hecho (la tabla
   estaba vacía al aplicar la migración) en vez de citar el docstring que desaparece.
2. `sdd/specs/access-notifications.md:538` — «Valores de enum **sin escritor**», sobre
   `LegalRegistrationStatus.MANUAL_REVIEW`. Los enums están **fuera de alcance** por el
   proposal, y siguen estándolo: la línea se reescribe a «valores de enum que nadie escribe
   todavía». Tres palabras, ninguna pérdida de significado, y R1.4 pasa al pie de la letra
   sobre un artefacto que este change no reclama.
3. `sdd/roadmap/rule11-ownership-single-source.md:3` — la nota de este change. **Se queda tal
   cual**, con su entrada en la lista de excepciones del guardián y el motivo escrito: es un
   diagnóstico de la patología, no una atribución, y R2.4 conserva lo que la enuncia para
   refutarla.
4. **`backend/tests/test_rule11_ownership.py` — la cuarta línea, que este apartado no previó
   porque el fichero no existía al escribirlo** (anotado en `/sdd:run`). El guardián contiene
   los dos literales *como vocabulario de detección*: `"sin escritor"` y
   `"nothing writes here yet"` son entradas de `OWNERSHIP_PATTERNS`. No es una copia de la
   atribución sino la herramienta que implementa R1.4.

> **Enmienda de `/sdd:run` (2026-08-18, hallazgo del panel de `/sdd:review`).**
> La frase final de este punto 4 decía que el guardián «no se reclama a sí mismo porque recorre
> `sdd/`, `docs/`, `backend/app/` y `backend/alembic/versions/`, **nunca `backend/tests/`** — que
> es deliberado y no un descuido». **Eso dejó de ser verdad durante `/sdd:run` y este documento
> no se actualizó.** `_code_files()` (`backend/tests/test_rule11_ownership.py`) recorre
> `("app", "alembic/versions", "tests")`.
>
> El motivo del cambio: el panel de seguridad de §5 encontró **cuatro copias dentro de
> `backend/tests/`** (`audit/test_change_set_property.py`,
> `maintenance/test_free_text_sink_contract.py` y dos en `notifications/test_escalate_slas.py`)
> que el barrido original no recorría — los sitios 22 a 25. Excluir `tests/` habría sido dejar
> fuera del guardián el sitio donde acababan de aparecer cuatro copias.
>
> Consecuencia sobre la razón por la que el guardián no se reclama a sí mismo: **ya no es que no
> recorra `tests/`, es una excepción declarada** —`DECLARED_EXCEPTIONS["backend/tests/test_rule11_ownership.py"]`,
> con su motivo escrito— porque sus dos ejes SON el vocabulario y se reclamaría entero. Es una
> exención de fichero completo, y `test_every_declared_exception_still_earns_its_place` la obliga
> a seguir reclamando algo para no caducar.

Consecuencia normativa, dicha para que no se lea como un descuido: **R1.4 se cumple con una
excepción declarada, no en su lectura literal.** El guardián de D6 es la forma durable de esa
comprobación; el `grep` de R1.4 es su antecesor más débil y se corre igual en Verification.

Rejected: reescribir la nota del roadmap para que no contenga el literal — R1.4 pasaría sin
excepciones, a cambio de borrar el enunciado del criterio que motivó el change del único sitio
donde consta que se pidió.

Rejected: dejar las tres y ampliar las exclusiones del `grep` — dos de las tres se arreglan de
verdad por céntimos, y ampliar la exclusión es lo que convierte un criterio en un adorno.

### D7 — El guardián vive en la suite del backend y ve `sdd/`/`docs/` por bind-mount de solo lectura, con centinela

**Elegido:** `backend/tests/test_rule11_ownership.py`, y `docker-compose.yml` monta
`./sdd:/workspace/sdd:ro` y `./docs:/workspace/docs:ro` en el servicio `backend`. La
resolución de raíz copia el patrón ya en uso
(`test_workflow_to_endpoint_wiring.py:41-50`): variable de entorno si está, luego
`/workspace/…`, luego `Path(__file__).resolve().parents[3]/…` para CI y para el host.

**Y un centinela fail-closed, que es la mitad que el precedente no necesitaba**: un bind
mount cuyo origen falta **lo crea Docker como directorio vacío**, así que sin centinela el
guardián recorrería un árbol de cero ficheros y pasaría en verde. El test exige que
`<raíz>/steering/security.md` exista, contenga la cabecera de la tabla de la regla 11, y que
el barrido vea un mínimo de ficheros Markdown; si no, `pytest.fail` — nunca `skip`, que en
`-rs` se lee como «no aplicaba».

Rejected: un script de repositorio o un hook de pre-commit — R3.1 pide explícitamente un
test de la suite del backend, y un guardián que solo corre en el gancho de quien lo tenga
instalado no es el fallo en rojo que R3 compra.

Rejected: montar la raíz del repositorio en `/workspace` — arrastra `node_modules`,
`media/` y `.git` a un contenedor que hoy no los ve, para leer dos árboles de Markdown.

Rejected: recorrer solo `backend/` y aceptar que los nueve sitios de `sdd/` no tengan
guardián — deja sin vigilancia justo el sitio donde nació la copia número ocho.

> **Enmienda de `/sdd:run` (2026-08-18, hallazgo del panel de `/sdd:review`).** Dos detalles de
> este apartado no describen lo que se construyó:
>
> 1. **No hay variable de entorno.** Este apartado (y la sección *Data & interfaces*) decían que
>    la resolución de raíz empieza por «variable de entorno si está», copiando el patrón de
>    `PROVENANCE_WORKFLOW_PATH`. `_prose_roots()` tiene **dos** candidatos y ninguna variable, y
>    la omisión es deliberada: una variable de entorno aquí sería la forma de una línea de
>    apuntar el barrido a un directorio vacío y **derrotar al centinela** que este mismo apartado
>    introduce. Es más estricto que lo diseñado, no un hueco. Queda escrito en el propio fichero.
> 2. **El índice es otro.** El fallback no es `Path(__file__).resolve().parents[3]` —ese es el
>    índice correcto en el test hermano, que está un nivel más abajo— sino `parents[1]` para
>    `BACKEND_ROOT` y su `.parent` para la raíz del repositorio. Verificado en CI: resuelve bien
>    con `working-directory: backend` sobre el checkout completo.

### D8 — El invariante «sesión sin marcar» pasa a `require_unmarked_session` en `app/core/db.py`

**Elegido:** una función `require_unmarked_session(session, *, read: str)` en
`backend/app/core/db.py`, junto a `bind_session_to_tenant` y al listener, que lanza
`TenantMarkedSessionError` nombrando la lectura y la precondición. Las cuatro lecturas la
invocan como primera sentencia de su cuerpo (R6.1, R6.2).

El sitio **no es una preferencia**: `test_session_marking.py:67` prohíbe leer `session.info`
en cualquier módulo de `app/` que no sea `core/db.py`. La alternativa sería relajar ese test,
que es exactamente el guardián que impide desarmar el filtro global.

El error va en `backend/app/core/tenancy.py`, cuyo docstring ya declara la familia: no es un
`AppError`, llegar ahí es un error de programación, tiene que salir como 500 y arreglarse,
nunca capturarse. Es el mismo carácter que `CrossTenantWriteError`.

Rejected: `ValueError` — indistinguible de los dos rechazos de `bind_session_to_tenant`, que
un `pytest.raises(ValueError)` de R6.3 confundiría con el suyo.

Rejected: un decorador sobre los cuatro métodos — el nombre de la lectura que R6.2 exige en
el mensaje habría que pasárselo igual, y esconde en un envoltorio la única línea que hace
que el lector del método vea la precondición.

Rejected: imponerlo en el listener con un `execution_options(unscoped_read=…)` que haga
`raise` en vez de filtrar. Es más estructural sobre la **sentencia**, pero declarar la opción
es tan olvidable como llamar al guard, añade acoplamiento de cada adaptador a una opción de
Core, y no alcanza la primera limitación del propio listener (SQL textual). Se anota porque
es la vía a la que mirar si algún día el residual de D9 duele.

### D9 — La enumeración de lecturas no scoped deja de ser prosa: es el conjunto de llamantes del guard

**Elegido:** un test estático en `backend/tests/test_unscoped_reads.py` afirma que el
conjunto de `(módulo, función)` que invocan `require_unmarked_session` en `app/` es
**exactamente** los cuatro declarados. Añadir un llamante sin declararlo es rojo; quitar una
llamada es rojo. El docstring de `find_by_email_globally` se recorta a una cita del guard y
del límite 2 (R6.5), y las cuatro specs que hoy apuntan a ese docstring como «el único
sitio» —`auth-tenancy.md:45`, `auth-account-recovery.md:329`, `guest-portal-api.md:354`,
`seed-data-demo.md:538`— se repuntan al guard.

Esto es lo que resuelve el hallazgo de Context: el recuento en prosa dice **tres** y son
**cuatro**, tercera vez que se queda obsoleto. Un número que un test afirma no se queda
obsoleto en silencio.

**Residual, escrito en el test**: lo que no detecta es una **quinta** lectura no scoped
completamente nueva que ni llame al guard ni se declare. La convención de nombrado `*_globally`
ya está declarada no exhaustiva por dos specs (la del portal no lleva el sufijo, la de
`cleaning` tampoco), así que no hay barrido sintáctico que la reclame; lo que hay es que
cualquier `select` sin `tenant_id` en un adaptador es un diff que un revisor ve, y el panel
de tenancy lo tiene en su lista.

Rejected: mantener el recuento en el docstring y añadirle la cuarta — arregla la copia y no
la patología, que es literalmente el argumento de cabecera del proposal.

> **Enmienda de `/sdd:review` (2026-08-18, hallazgo del panel de seguridad, confirmado por
> arquitectura).** Este apartado decía —y lo repetía la prosa que instaló en ocho sitios— que
> «el conjunto de llamantes del guard **es** la enumeración» de las lecturas no scoped. **Eso es
> falso, y falso por la misma clase de exceso que este change existe para eliminar.**
>
> Hay **dos clases** de lectura que exigen sesión sin marcar, y este censo cubre una:
>
> 1. **Las que resuelven el tenant a partir de la fila que leen** — las cuatro declaradas. Es la
>    clase que el censo audita.
> 2. **Los drenajes de cola sobre un `tenant_id` nullable** — `select_pending` y `lease`
>    (`app/integrations/infrastructure/repositories.py`). Exigen sesión sin marcar por un motivo
>    distinto: una sesión marcada esconde las filas `tenant_id IS NULL` sin error. No llaman al
>    guard; los pina `test_tenant_filter.py`.
>
> Y hay **una omisión genuina de la clase 1**: `find_by_token_hash` (mismo módulo) resuelve el
> tenant de la fila igual que las cuatro, y no llama al guard. Su seguridad hoy descansa en la
> forma de la clave (256 bits de CSPRNG tras un índice `UNIQUE`), no en el guard.
>
> **Lo elegido: acotar la afirmación en los ocho sitios, no extender el guard**, y dejar la
> omisión declarada en vez de tapada. `KNOWN_UNGUARDED_UNMARKED_READS`
> (`backend/tests/test_unscoped_reads.py`) fija las tres lecturas en las dos direcciones —
> enrojece si una desaparece y enrojece si alguna empieza a llamar al guard—, así que la
> declaración no es prosa que pueda podrirse.
>
> **Por qué `find_by_token_hash` no se guarda aquí, dicho como deuda y no como decisión cerrada**:
> arquitectura señaló con razón que su único llamante de producción
> (`app/integrations/application/webhooks.py:267`, ruta anónima de webhook) ya corre siempre sin
> marcar, así que añadir el guard sería una red de seguridad y no un cambio de comportamiento. No
> se hizo porque **hay trece sitios de test que la invocan directamente sobre `db_session`**
> (`tests/integrations/test_webhook_endpoints.py`, `test_webhook_provisioning.py`) y el demonio de
> Docker estaba caído en esta fase, así que no se pudo demostrar que la suite siga verde. Guardarla
> es el siguiente paso natural y requiere una pasada de suite, no un debate.

### D10 — Las dos copias de `cleaning` citan la precondición real y el límite 2

**Elegido:** en `backend/app/cleaning/api/dependencies.py:298` y
`backend/app/cleaning/infrastructure/repositories.py:534` desaparece «the only place that
marks» y queda la precondición que de verdad se cumple —la sesión de esta ruta no se marca
nunca, porque el endpoint no declara `require(...)`— más una cita al límite 2 de
`_scope_statement_to_tenant` y al guard de D8, sin reproducir el censo de quién marca
(R5.1, R5.2). Tras el barrido,
`grep -rn "only place that marks\|only thing that marks" backend/app` devuelve **solo**
`backend/app/auth/infrastructure/repositories.py:120`, que lo enuncia para refutarlo
(R5.3, R2.4).

Rejected: enumerar los que sí marcan (`get_authenticated_request`, `SessionTenantBinder`,
cada CLI) — es la lista que R2.4 y el propio docstring de `find_by_email_globally` declaran
imposible de mantener.

### D11 — Los recuentos internos obsoletos

**Elegido:** `WebhookEventModel:51` («el más expuesto de **las seis**») pasa a decir «de las
del censo» sin cifra, porque la cifra es de la tabla y este docstring no la gobierna;
`sdd/specs/domain-foundation-financial.md:49-50` pierde el «Siete columnas» y el «una
**única** excepción» / «los tres docstrings la citan sin repetirla» (son cuatro excepciones
desde `messaging-ai`, y los tres docstrings la repiten), y queda con lo local: las columnas
que **esta capacidad** introduce son sumideros y su contrato es la regla 11. Cubre R4.5.

Rejected: actualizar las cifras a las de hoy — un recuento en un sitio que no lo gobierna se
vuelve a quedar obsoleto en el siguiente change, que es cómo estas tres llegaron aquí.

### D12 — `domain-foundation-core.md:31` no se toca, y consta por qué

**Elegido:** intacto. Habla de cifrado en reposo (regla 3), no del censo de la regla 11, y la
tabla no lo gobierna (R2.3). El guardián de D6 no lo reclama porque su eje de sumidero se
alimenta de las dieciséis columnas de la tabla y `wifi_password_encrypted` /
`document_number_encrypted` no están en ella.

### D13 — Los tests que hoy afirman el filtrado silencioso pasan a afirmar el fallo

**Elegido:** los tests que sobre una sesión marcada esperan que una de las cuatro lecturas
devuelva `None` cambian a `pytest.raises(TenantMarkedSessionError)`. No es «modificar un
caller legítimo» (R6.4): esas aserciones **documentaban el peligro** que el guard convierte
en fallo, así que su forma correcta después de este change es la contraria.

> **Enmienda de `/sdd:run` (2026-08-17, aprobada por Jose en el gate de la desviación).**
> La medición que este apartado dejaba abierta salió **44 rojos**, y su forma **no es la que
> esta decisión predijo**: ni uno solo pertenece a las dos clases de arriba. Ninguno afirma el
> filtrado silencioso y ninguno es un caller legítimo roto — los 44 afirman comportamiento
> ordinario (servir una foto, resolver una estancia, cambiar una contraseña) y caen porque
> **24 fixtures entregan a la app una única `db_session` compartida por todas las peticiones
> del test**, de modo que una petición autenticada deja la sesión marcada para la siguiente.
> Producción abre una sesión por petición y no puede alcanzar la secuencia.
>
> Reparto: `test_serve_photo_api.py` 14, `test_seed_demo.py` 12, `test_recovery_api.py` 10,
> `test_portal_api.py` 6, `test_user_admin_api.py` 2.
>
> **Lo elegido es reproducir la única propiedad de la sesión-por-petición de la que dependen
> esas lecturas: `request_session_override` (`tests/conftest.py`) borra el marcador de tenant
> al terminar cada petición.** Misma sesión, misma conexión, misma transacción, misma
> visibilidad de filas sin commitear. Lo usan cuatro fixtures (la raíz, `cleaning/conftest.py`
> y las dos de `test_portal_api.py`), y `test_seed_demo.py` lleva el equivalente en un envoltorio
> local de `apply_plan`, porque cada `make seed-demo` es un proceso nuevo. Suite completa en
> verde: **7349 pasados, 39 saltados, 0 fallos** (medido de nuevo en `/sdd:review`; la cifra que
> este párrafo dio primero, 7340, se tomó antes de añadir los tests nuevos del guard).
>
> Y **una** aserción sí se tocó, al contrario de lo que dijo la primera versión de esta enmienda:
> en `tests/guests/test_portal_api.py`, `assert db_session.info[TENANT_ID_SESSION_KEY] == tenant_b.id`
> pasó a `assert api.bound_tenants == [tenant_b.id]` más `assert TENANT_ID_SESSION_KEY not in
> db_session.info`. Es un **refuerzo** y no una relajación —la anterior observaba el residuo de la
> fixture, la nueva observa el `bind` que hace la app—, y salió del panel de seguridad de §1, que
> demostró por mutación que es la única aserción que caza un binder anulado en la raíz de
> composición. Pero «sin tocar ninguna aserción» era falso, y en este change eso importa.
>
> Que sea código de test no es una puerta trasera al guard: `test_session_marking.py` prohíbe
> esto en `app/`, donde desmarcar a media petición apagaría el filtro global el resto de la
> sesión. Aquí la petición ya terminó, y la siguiente habría tenido una sesión nueva en
> producción.
>
> **Las dos formas fieles se midieron y las dos cuestan más de lo que dan**, que es lo que
> mantiene `test-session-per-request` en el roadmap y fuera de este change: una sesión por
> petición sobre su propia conexión deja invisibles las filas de setup sin commitear (**249
> rojos** solo en `auth` y `cleaning`); todas las sesiones sobre una conexión compartida las
> conserva visibles, pero `join_transaction_mode` convierte el `commit()` de cada caso de uso
> en la liberación de un savepoint —un cambio de significado de toda la suite que rompió tests
> de concurrencia y atomicidad en `scheduler`, `messaging`, `notifications` e `integrations`
> que no tienen nada que ver con ninguna lectura no scoped (**40 rojos**, en sitios que este
> change no toca).

La causa es la fixture: `backend/tests/conftest.py:222-225` sustituye `get_db_session` por
**una sola** `db_session` para todo el test, mientras producción abre una por petición. Un
test que autentica —lo que marca esa sesión— y después golpea una ruta anónima ejecuta una de
las cuatro lecturas sobre una sesión marcada, cosa que en producción no pasa.
`backend/tests/auth/test_recovery_api.py:1131` ya lo documenta como divergencia conocida.

Rejected: hacer que la fixture `api` abra una sesión por petición. Es el arreglo de verdad y
está fuera de alcance: los tests insertan filas por `db_session` y esperan que la API las
vea, así que el cambio obliga a revisar el `commit` de toda la suite. **No va a `BLOCKED.md`**
—no es trabajo pendiente de este change, y una entrada ahí bloquearía el ship— sino a la
lista de candidatos de roadmap que `/sdd:archive` traslada, con el nombre propuesto
`test-session-per-request`. Su valor no es cosmético: mientras la fixture comparta sesión, la
suite no ejercita la sesión-por-petición que sí tiene producción.

Rejected: eximir del guard a las sesiones «de test» — un guard con una puerta de test no es
un guard.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Autoridad (regla 11) | `sdd/steering/security.md` | Fila `audit_logs.changes` → punto de paso (D4). Fila `notification_logs.subject`/`body` → **partida en dos** (D5b), con la entrada de `maintenance`+`cleaning` en la fila (b) (D5). Prosa: cierre del hueco que `security.md:124` declara. Sin contratos nuevos ni excepciones ampliadas (R4.6) |
| Modelos ORM | `backend/app/notifications/infrastructure/models.py`, `backend/app/audit/infrastructure/models.py`, `backend/app/integrations/infrastructure/models.py` | Quitar atribución y afirmaciones falsas; conservar sumidero + regla 11 + razonamiento local + mecanismo (D1). Recuento de `WebhookEventModel` (D11) |
| Dominio (value objects) | `backend/app/audit/domain/value_objects.py`, `backend/app/notifications/domain/results.py`, `backend/app/cleaning/domain/notifications.py` | Tres copias que R1.2 no lista (D2): quitar «first writer», conservar el mecanismo estructural |
| Migración | `backend/alembic/versions/a4d17e83b6c1_reservations_webhooks.py` | La justificación de seguridad afirma el hecho (tabla vacía al aplicarla) en vez de citar un docstring que desaparece (D2) |
| Guard de sesión | `backend/app/core/db.py`, `backend/app/core/tenancy.py` | `require_unmarked_session` + `TenantMarkedSessionError` (D8) |
| Las cuatro lecturas | `backend/app/auth/infrastructure/repositories.py` (`find_by_email_globally`, `consume_globally`), `backend/app/guests/infrastructure/portal_repositories.py` (`find_live_by_token_hash`), `backend/app/cleaning/infrastructure/repositories.py` (`locate_without_tenant_scoping`) | Invocar el guard; recortar el docstring a una cita del guard y del límite 2 (R6.5, D9) |
| Copias de `cleaning` (R5) | `backend/app/cleaning/api/dependencies.py`, `backend/app/cleaning/infrastructure/repositories.py` | Quitar «the only place that marks»; precondición real + cita al límite 2 (D10) |
| Límite 2 | `backend/app/core/db.py` | El párrafo del límite 2 remite al guard como sitio donde el invariante pasa a vivir |
| Tests nuevos | `backend/tests/test_rule11_ownership.py`, `backend/tests/test_unscoped_reads.py` | Guardián de propiedad (D6, D7) y guardián + censo de lecturas no scoped (D8, D9) |
| Tests afectados | `backend/tests/test_tenant_filter.py`, `backend/tests/auth/test_recovery_api.py`, `backend/tests/auth/test_isolation.py`, y los que el barrido de `/sdd:run` encuentre | `pytest.raises` donde hoy se afirma el filtrado silencioso (D13) |
| Compose | `docker-compose.yml` | `./sdd:/workspace/sdd:ro` y `./docs:/workspace/docs:ro` en `backend` (D7) |
| Specs | `sdd/specs/domain-foundation-financial.md`, `user-management.md`, `cleaning.md`, `access-notifications.md` (207, 217, 255), `reservations-webhooks.md`, `messaging-ai.md` | Citar la tabla, sin reproducir la atribución (D1, D11) |
| Spec (residuo de R1.4) | `sdd/specs/access-notifications.md:538` | «valores de enum sin escritor» → «que nadie escribe todavía»; los enums siguen fuera de alcance (D6b) |
| Specs (lecturas no scoped) | `sdd/specs/auth-tenancy.md`, `auth-account-recovery.md`, `guest-portal-api.md`, `seed-data-demo.md`, `cleaning.md` | Repuntar «la enumeración vive en un solo sitio» del docstring al guard (D9); `cleaning.md` documenta su lectura no scoped, hoy ausente |
| Roadmap | `sdd/roadmap/user-management.md`, `sdd/roadmap/access-notifications.md` | Quitar la atribución de sumidero; conservar lo demás intacto |

## Data & interfaces

- **Esquema**: ninguno. Sin migración, sin columna, sin enum.
- **API**: ninguna. Ningún endpoint, ningún esquema de respuesta, `backend/openapi.json`
  intacto.
- **Interfaz nueva**: `require_unmarked_session(session: AsyncSession, *, read: str) -> None`
  en `app/core/db.py`, y `TenantMarkedSessionError(RuntimeError)` en `app/core/tenancy.py`.
- **Puertos**: sin cambios. El guard se invoca en los adaptadores; los `Protocol` de
  `domain/ports.py` no lo mencionan, porque no tienen sesión.
- **Config / env**: ninguna variable nueva, **y tampoco la variable opcional** que este apartado
  anunciaba para la raíz de prosa del guardián. Se descartó al construirlo: sería la forma de una
  línea de apuntar el barrido a un directorio vacío y derrotar al centinela de D7 (ver su
  enmienda). La resolución tiene dos candidatos fijos, `/workspace/…` y el layout del repositorio.
- **Compose**: dos bind-mounts de solo lectura en el servicio `backend` de
  `docker-compose.yml`. `docker-compose.deploy.yml` no se toca: no corre la suite.
- **Contrato de la regla 11**: sin cambios (R4.6). El diff de `security.md` mueve y completa
  atribución; no deriva ninguna forma nueva ni ensancha ninguna excepción.

## Risks & mitigations

- **El guard rompe un número desconocido de tests por la sesión compartida de la fixture**
  (D13). Es el riesgo dominante y no se puede acotar desde el design: el stack de este
  worktree no está arrancado, así que la cifra sale en `/sdd:run`. Mitigación: la primera
  tarea después de introducir el guard es correr la suite completa y clasificar cada rojo en
  «afirmaba el filtrado silencioso» (se convierte en `pytest.raises`) o «caller legítimo
  roto» (entonces es el guard lo que está mal, no el test). Candidatos ya localizados:
  `test_tenant_filter.py`, `test_recovery_api.py`, `test_isolation.py`,
  `test_route_authorization.py` (recorre todas las rutas).
- **El bind mount ausente vuelve verde el guardián.** Docker crea el origen que falta como
  directorio vacío. Mitigado por el centinela de D7, que exige la cabecera de la tabla y un
  mínimo de ficheros, y falla en vez de saltarse.
- **El guardián reclama sitios legítimos y su lista de excepciones crece hasta no significar
  nada.** Mitigado por los dos ejes de D6 (que bajan los candidatos de veinte a los del
  censo) y por la obligación de motivo escrito en cada entrada.
- **La lista de excepciones se usa para silenciar la copia número nueve** en vez de para
  documentar un falso positivo. No hay mecanismo que lo impida; lo que hay es que la entrada
  lleva motivo y aparece en el diff de un PR.
- **`docker compose exec backend uv run pytest` sobre un contenedor ya levantado no ve el
  mount nuevo** hasta un `make down && make up`. Se dice en la sección Verification para que
  no se lea como un fallo del guardián.
- **R6.4 y el orden de las tareas**: si el guard entra antes de que los cuatro docstrings se
  recorten, la suite queda roja entre dos tareas. `/sdd:tasks` debe poner el guard y la
  clasificación de rojos en la misma sección.
- **La suite del backend crece en dos ficheros de barrido de árbol.** El coste es de decenas
  de milisegundos por fichero leído; `test_layering.py` y `test_session_marking.py` ya
  recorren `app/` entero. Sin impacto medible sobre los 205 s de CI.

## Open questions

Ninguna abierta. Las tres que este design levantó se resolvieron en el gate de
`/sdd:design` (aprobadas por Jose) y viven ya como decisiones, con sus alternativas
rechazadas:

| Pregunta | Resuelta en | Resolución |
|---|---|---|
| ¿Se parte la fila `notification_logs.subject`/`body` entre la licencia (excepción 1, sin escritor vivo) y el contrato vivo («constante más identificadores»)? | **D5b** | Sí. Ninguno de los cinco escritores vivos ejerce la excepción 1; la fila les atribuía una licencia que ninguno toma |
| ¿El guardián excluye `sdd/changes/` entero y `docs/adr/`, y no solo `sdd/changes/archive/`? | **D3** | Sí, amplía la letra de R3.3: un registro de change es el mismo documento antes y después del `mv` |
| ¿Qué se hace con las líneas que sobreviven a la comprobación literal de R1.4? | **D6b** | Dos se arreglan (la migración y la línea de enums); la nota de roadmap de este change se queda con una excepción declarada y su motivo |

Lo que queda **sin decidir a propósito**, y no es una pregunta para el gate sino una medición
que le toca a `/sdd:run`: cuántos tests rompe el guard de D8 por la sesión compartida de la
fixture (D13, primer punto de Riesgos). No se puede acotar desde aquí sin levantar el stack, y
la respuesta no cambia ninguna decisión de este documento — solo el tamaño de una tarea.
