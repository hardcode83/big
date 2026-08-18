# Proposal: rule11-ownership-single-source

## Why

La regla 11 de `sdd/steering/security.md` dice de sí misma que su contrato vive en un
solo sitio, y es verdad. Lo que **no** vive en un solo sitio es la **propiedad**: quién
escribe cada sumidero hoy y quién lo heredará está reafirmado fuera de la tabla, y cada
revisión encuentra una copia más desincronizada. El recuento fue 4 → 5 → 6 en rondas
sucesivas del panel de `celery-jobs` (2026-08-05), arreglando una y descubriendo la
siguiente; `seed-data-demo` (2026-08-12) encontró la séptima.

Hoy, verificado sobre este árbol, **tres de esas copias no están desactualizadas sino que
afirman algo falso**:

- `AuditLogModel` dice *«Nothing writes here yet; `user-management` … inherit the
  contract»* (`backend/app/audit/infrastructure/models.py:22`). No es que se le haya
  quedado corto un escritor: **doce módulos** llaman a `AuditLogFactory.build` hoy
  (`access`, `auth/user_admin`, `auth/recovery`, `cli/reset_password`, `cli/seed_demo`,
  `tenants`, `integrations/cli/pms_credentials`, `integrations/application`, `properties`,
  `maintenance`, `cleaning`, `guests`). Es la copia más podrida del censo.
- `NotificationLogModel` dice *«`last_error` still has no writer; `access-notifications`
  inherits that one when it adds delivery»*
  (`backend/app/notifications/infrastructure/models.py:28`). `access-notifications` lo
  escribe desde 2026-08-08, y la fila tiene además dos escritores más de `subject`/`body`
  (`auth-account-recovery`, `messaging-ai`) que el docstring no menciona.
- `sdd/specs/domain-foundation-financial.md:50` dice *«una única excepción»*. Son
  **cuatro** desde `messaging-ai` (2026-08-16). La misma línea afirma que *«los tres
  docstrings la citan sin repetirla»*, y los tres la repiten.

**La misma patología tiene un segundo sumidero**, y esta entrada barre los dos de una
pasada (anotado el 2026-08-12 desde §2 y §3 del `BLOCKED.md` de `seed-data-demo`): el
invariante *«esta lectura tiene que correr antes de que nadie marque la sesión con un
tenant»* está reafirmado en cuatro ficheros y **no tiene ninguna forma ejecutable**. Dos
de esas copias afirman que `get_authenticated_request` es *«the only place that marks»*
(`backend/app/cleaning/api/dependencies.py:298`,
`backend/app/cleaning/infrastructure/repositories.py:534`), y eso es **falso** desde
`guest-portal-api` (merged 2026-08-11): `SessionTenantBinder.bind` marca la sesión de la
request en las rutas anónimas del portal, y cada comando CLI marca la suya. No hay
defecto funcional hoy —los dos routes de `cleaning` están correctamente cableados a
sesiones que nunca se marcan— pero el enunciado es exactamente el atajo que la autoridad
existe para refutar, y quien consulte la copia en vez de la autoridad readquiere la
creencia.

El arreglo **no es corregir la copia número siete**. El docstring de
`find_by_email_globally` es la prueba: narra él mismo haber quedado obsoleto dos veces,
concluye que *«a list nobody can be made to update is worse than no list»*, y en ese
mismo change estrenó dos afirmaciones falsas nuevas que el panel tuvo que corregir. La
prosa no se puede obligar a estar al día; un test y un `raise` sí.

**Y mientras se escribía esta propuesta nació la copia número ocho**, que es el dato que
zanja la discrepancia del panel de `seed-data-demo` (seguridad dijo que bastaba con
remitir a la autoridad; tenancy dijo que remitir no impide leer la afirmación como un
hecho). Al archivar `messaging-ai` el 2026-08-17, `sdd/specs/messaging-ai.md:94` quedó
así: *«declarar `messages.content`, `messages.intent` y `messages.metadata` en el censo de
la regla 11 …, único sitio donde vive ese contrato, **con esta capability como primer
escritor vivo**»* — una frase que cita la autoridad y reafirma la propiedad en el mismo
aliento. Quien la escribió tenía la entrada de este roadmap delante y aun así la escribió,
porque la forma natural de redactar una spec es declarar quién estrena la columna. Eso es
evidencia empírica, no argumento: la remisión a la autoridad **no** impide la copia. Solo
un guardián que falle en rojo lo hace, y de ahí R3.

Fuentes: `sdd/roadmap/rule11-ownership-single-source.md` (entrada y sus dos
ampliaciones), `sdd/steering/security.md` §«Sumideros de texto en claro (regla 11)»,
límite 2 del docstring de `_scope_statement_to_tenant` (`backend/app/core/db.py`).

## What changes

Después de este change, **la propiedad de cada sumidero de la regla 11 se declara en un
único sitio —la tabla de `steering/security.md`— y ningún otro artefacto la reafirma**:
cada docstring, spec y entrada de roadmap que hoy nombra al escritor pasa a citar la
tabla, conservando lo que sí es información local. Esa tabla queda además **completa**
para las columnas que el barrido toca, y —esto es lo que la hace no repetible— **completa
sin listas de módulos**: donde el contrato se impone en un punto único de paso, la tabla
declara ese punto (`audit_logs.changes` → `AuditLogFactory` + `ChangeSet`, con doce
llamantes que ya no hace falta enumerar); donde no lo hay, declara una fila por contrato
(`notification_logs.subject`/`body`, cuyos tres escritores omitidos entran así). Los
recuentos internos que hoy mienten («las seis», «una única excepción», «los tres
docstrings») dejan de hacerlo. Y la deduplicación deja de depender de que alguien se
acuerde: **un test recorre el árbol y falla si aparece la copia número nueve**.

En paralelo, el invariante «sesión sin marcar» gana lo que le falta en las dos mitades
que el panel de `seed-data-demo` no consiguió cerrar discutiendo: las dos copias de
`cleaning` dejan de afirmar el atajo refutado y citan el límite 2, y **las cuatro
lecturas no scoped del sistema pasan por un guard compartido que rechaza una sesión ya
marcada** — un fallo en rojo en lugar de un párrafo.

No cambia ningún contrato de la regla 11, ninguna excepción, ningún comportamiento de
producto. Es un change de propiedad de la información y de una precondición que pasa de
prosa a código.

## Requirements

### R1 — La propiedad de un sumidero se declara solo en la tabla de la regla 11

**Como** quien lee un modelo o una spec para saber qué contrato le aplica a una columna,
**quiero** que la atribución de escritor viva en un único sitio, **para** no adquirir una
creencia falsa de una copia que nadie ha podido mantener al día.

Criterios de aceptación:

1. WHERE un artefacto fuera de la tabla de la regla 11 declara **quién escribe** o
   **quién heredará** un sumidero, THE SYSTEM SHALL sustituir esa declaración por una
   cita a la tabla, sin reproducir la atribución.
2. THE SYSTEM SHALL aplicarlo a estos sitios, verificados sobre este árbol:
   `backend/app/notifications/infrastructure/models.py` (`NotificationLogModel`),
   `backend/app/audit/infrastructure/models.py` (`AuditLogModel`),
   `backend/app/integrations/infrastructure/models.py` (`WebhookEventModel`),
   `backend/alembic/versions/a4d17e83b6c1_reservations_webhooks.py`,
   `sdd/specs/domain-foundation-financial.md` (líneas 50 y 52),
   `sdd/specs/user-management.md:11`, `sdd/specs/cleaning.md:265`,
   `sdd/specs/access-notifications.md` (líneas 217 y 255),
   `sdd/specs/reservations-webhooks.md:218`, `sdd/specs/messaging-ai.md:94`,
   `sdd/roadmap/user-management.md` y `sdd/roadmap/access-notifications.md`.
3. THE SYSTEM SHALL tratar `sdd/specs/access-notifications.md:217`
   (*«`GUEST_ESCALATION` ganó su primer escritor el 2026-08-16»*) como copia **dentro** de
   alcance, aunque nombre un miembro de enum y no una columna: la tabla ya atribuye ese
   aviso a `messaging-ai` en la fila de `notification_logs.subject`/`body`, así que es la
   misma propiedad declarada dos veces. El criterio es qué hecho se duplica, no de qué
   tipo es el objeto que lo lleva.
4. WHEN el barrido termina, THE SYSTEM SHALL dejar que
   `grep -rn "sin escritor\|Nothing writes here yet"` sobre el árbol de trabajo no
   devuelva ninguna línea fuera de `sdd/steering/security.md` y de
   `sdd/changes/archive/`.
5. IF una copia afirma algo que hoy es falso (`AuditLogModel`, `NotificationLogModel`,
   `domain-foundation-financial.md:50`), THEN THE SYSTEM SHALL eliminar la afirmación en
   vez de corregirla — el objetivo es que no haya una novena versión que corregir.

### R2 — Lo que es información local se queda, y el barrido no se pasa de largo

**Como** quien lee `AuditLogModel` sin abrir el steering, **quiero** seguir sabiendo que
esa columna es un sumidero de texto en claro y que su contrato es la regla 11, **para**
que quitar la duplicación no me deje sin la señal que me manda a la autoridad.

Criterios de aceptación:

1. THE SYSTEM SHALL conservar en cada sitio (a) que la columna es un sumidero de texto en
   claro, (b) que su contrato es la regla 11 de `steering/security.md`, y (c) el
   razonamiento **local** de por qué esa columna es peligrosa en ese módulo —el índice de
   `audit_logs`, la ruta del código de acceso de PRD §17 por `body`, el `payload`
   persistido verbatim de PRD §7.26.
2. THE SYSTEM SHALL conservar los mecanismos que hacen cumplir el contrato por
   construcción cuando el sitio es donde viven (`ChangeSet`, `AuditLogFactory`,
   `WebhookEventFailure`, `scrub_card_data`): son hechos sobre el código de ese módulo,
   no atribución de propiedad.
3. THE SYSTEM SHALL dejar intacto `sdd/specs/domain-foundation-core.md:31`
   (`wifi_password_encrypted`, `document_number_encrypted`): habla de cifrado en reposo
   (regla 3), no del censo de la regla 11, y su tabla no lo gobierna.
4. IF una frase enuncia el atajo o la creencia falsa **para refutarla** —como hacen los
   párrafos de `find_by_email_globally`—, THEN THE SYSTEM SHALL conservarla: refutar no
   es reafirmar.

### R3 — Un guardián automático impide la copia número nueve

**Como** revisor de un change futuro que estrene un sumidero, **quiero** que el árbol
falle en rojo si vuelvo a escribir la atribución fuera de la tabla, **para** que la
deduplicación no dependa de que un panel la encuentre por octava vez — y porque la copia
número ocho se escribió con esta misma entrada del roadmap delante.

Criterios de aceptación:

1. THE SYSTEM SHALL incluir un test de la suite del backend que recorra el árbol y falle
   cuando una declaración de propiedad de un sumidero aparezca fuera de
   `sdd/steering/security.md`.
2. WHEN el test falla, THE SYSTEM SHALL nombrar en el mensaje el fichero, la línea y la
   frase encontrada, y remitir a la tabla como el sitio donde va.
3. THE SYSTEM SHALL excluir del barrido `sdd/changes/archive/`, que son registros
   históricos que no se reescriben.
4. IF el guardián no puede reclamar un sitio que sí es una copia —el hueco que el propio
   steering documenta sobre `app/cli/seed_demo.py` y el guardián de `maintenance`—, THEN
   THE SYSTEM SHALL decir explícitamente en el test qué formas **no** detecta, en vez de
   dejar que su verde se lea como cobertura completa.

### R4 — La tabla queda completa, y su forma de declarar propiedad no puede podrirse

**Como** quien consulta la tabla porque a partir de ahora es la única fuente, **quiero**
que no tenga huecos conocidos **ni listas que nadie pueda mantener**, **para** que ser la
autoridad signifique algo más que ser el último sitio en desincronizarse.

El barrido destapó dos filas incompletas, y **no se arreglan igual** — la diferencia es si
el contrato se hace cumplir en un punto único de paso:

- **`audit_logs.changes`**: la fila nombra a `user-management` «y quien audite documentos
  de huésped», y hoy escriben **doce módulos**. Pero los doce pasan por
  `AuditLogFactory.build` + `ChangeSet`, que imponen el contrato **por construcción**.
- **`notification_logs.subject`/`body`**: la fila enumera cuatro changes y hay **siete**
  módulos que construyen `NotificationLog` directamente (`maintenance`, `cleaning` y
  `guests` no aparecen). Aquí no hay punto único de paso que imponga nada: cada escritor
  sostiene su contrato por disciplina.

Criterios de aceptación:

1. THE SYSTEM SHALL no sustituir un hueco por una lista de nombres de módulo: enumerar los
   doce escritores de `audit_logs.changes` sería exactamente la lista que nadie actualiza
   —la patología que este change existe para cerrar— y la copia número trece nacería con
   el siguiente módulo que audite algo.
2. WHERE una columna tiene un punto único de paso que impone su contrato por construcción,
   THE SYSTEM SHALL declarar **ese punto** como respuesta a «quién la escribe», en vez de
   sus llamantes: para `audit_logs.changes`, `AuditLogFactory.build` + `ChangeSet`, con la
   consecuencia dicha explícitamente —cualquier módulo puede escribir esa columna y
   ninguno puede derivar un contrato propio—.
3. WHERE una columna **no** tiene ese punto de paso, THE SYSTEM SHALL declarar una fila
   **por contrato** (no por módulo) y decir que la forma se sostiene por disciplina del
   llamante, como la tabla ya hace con el tercer escritor de `incidents.title`. Para
   `notification_logs.subject`/`body`, THE SYSTEM SHALL cubrir los tres escritores que la
   fila omite —`app/maintenance/domain/notifications.py`,
   `app/cleaning/domain/notifications.py`, `app/guests/application/use_cases.py`— tras
   comprobar a qué contrato se atiene cada uno.
4. IF alguno de esos tres no se atiene al contrato que ya hay para esa fila, THEN THE
   SYSTEM SHALL abrirle fila propia con su forma, y no ensanchar la excepción 1 por
   parecido —lo que el párrafo de cierre de la regla 9 prohíbe—.
5. THE SYSTEM SHALL corregir los recuentos internos que el barrido demuestra obsoletos:
   *«el más expuesto de **las seis**»* en `WebhookEventModel` (son dieciséis columnas,
   veinte filas) y *«una **única** excepción»* / *«los tres docstrings la citan sin
   repetirla»* en `domain-foundation-financial.md:50`.
6. WHEN la tabla se toque, THE SYSTEM SHALL no derivar ningún contrato nuevo ni ampliar
   ninguna excepción: este change declara propiedad, no concede nada.

### R5 — Las dos copias de `cleaning` dejan de afirmar el atajo refutado

**Como** quien lee por qué una query no lleva tenant, **quiero** que el docstring no me
diga que `get_authenticated_request` es el único sitio que marca, **para** no colocar un
caller detrás de un `bind` creyendo que su sesión está limpia.

Criterios de aceptación:

1. THE SYSTEM SHALL eliminar la afirmación *«the only place that marks»* de
   `backend/app/cleaning/api/dependencies.py:298` y de
   `backend/app/cleaning/infrastructure/repositories.py:534`.
2. THE SYSTEM SHALL sustituirla por la precondición real —la sesión de esa ruta no se
   marca nunca— más una cita al límite 2 del docstring de `_scope_statement_to_tenant`,
   sin reproducir el censo de quién marca.
3. WHEN el barrido termine, THE SYSTEM SHALL dejar que
   `grep -rn "only place that marks\|only thing that marks"` sobre `backend/app` devuelva
   únicamente la línea de `find_by_email_globally` que lo enuncia **para refutarlo**.

### R6 — El invariante «sesión sin marcar» tiene forma ejecutable

**Como** quien añade un caller a una lectura no scoped, **quiero** que el sistema me
rechace si mi sesión ya está marcada, **para** que la condición sea un fallo y no un
párrafo que puedo no leer.

Criterios de aceptación:

1. THE SYSTEM SHALL introducir un guard compartido que compruebe que la sesión recibida
   **no** lleva marcador de tenant, y THE SYSTEM SHALL invocarlo desde las cuatro
   lecturas no scoped del sistema: `find_by_email_globally`
   (`app/auth/infrastructure/repositories.py`), `consume_globally`
   (`app/auth/infrastructure/repositories.py`), `find_live_by_token_hash`
   (`app/guests/infrastructure/portal_repositories.py`) y
   `locate_without_tenant_scoping` (`app/cleaning/infrastructure/repositories.py`).
2. IF una de esas lecturas se invoca sobre una sesión ya marcada con un tenant, THEN THE
   SYSTEM SHALL fallar con un error que nombre la lectura y la precondición, **antes** de
   ejecutar la sentencia.
3. THE SYSTEM SHALL cubrirlo con un test por lectura que la invoque sobre una sesión
   marcada y exija el fallo; el test **no** puede apoyarse en observar filas, porque
   sobre una sesión marcada el listener filtra hasta el `select` de una columna y el caso
   no podría distinguirse de un resultado vacío legítimo.
4. WHEN el guard entre, THE SYSTEM SHALL dejar la suite completa del backend en verde sin
   modificar ningún caller legítimo: la secuencia de `app/cli/seed_demo.py` (lee sin
   marcar, marca después) y la de `GuestPortalAuthenticator` (resuelve el token sin
   marcar, hace `bind` después) siguen pasando.
5. WHERE el docstring de una de esas cuatro lecturas hoy sostiene la precondición en
   prosa, THE SYSTEM SHALL recortarla a una cita del guard y del límite 2 — el guard es
   ahora el sitio donde vive.

## Out of scope

- **Reescribir `sdd/changes/archive/`.** Los archivos son registros históricos (regla 8
  del flujo SDD): las copias que contienen se quedan como testimonio de lo que se creía
  entonces, y el guardián de R3 las excluye por eso.
- **`sdd/specs/domain-foundation-core.md:31`** y cualquier atribución de escritor que no
  sea de un sumidero de la regla 11 (cifrado en reposo, `cleaning_tasks`, enums sin
  escritor). Misma patología, censo distinto; si merece barrido, es entrada propia.
- **Ampliar el guardián de texto libre de `maintenance`/`messaging`**
  (`test_free_text_sink_contract.py`): vigilan el *contenido* que llega a las columnas,
  no la propiedad. Este change no toca su cobertura.
- **Que `IncidentClassifier`/`AIAdapter` dejen de poder devolver un tipo no declarado**:
  el steering ya lo declara abierto y lo remite a `backend-static-typecheck` en el
  roadmap.
- **Reclamar el hueco de `app/cli/seed_demo.py`** en el guardián de `maintenance`, que el
  propio steering documenta: R3.4 obliga a decirlo, no a cerrarlo.
- **Cualquier cambio de contrato, excepción o comportamiento de la regla 11.** R4.4 lo
  prohíbe explícitamente.

## Affected specs

- `sdd/specs/domain-foundation-financial.md` — es la spec que hoy duplica la propiedad de
  los siete sumideros originales (líneas 50 y 52); pasa a citar la tabla.
- `sdd/specs/user-management.md`, `sdd/specs/cleaning.md`,
  `sdd/specs/access-notifications.md`, `sdd/specs/reservations-webhooks.md`,
  `sdd/specs/messaging-ai.md` — cada una declara «primer escritor» de una columna del
  censo.
- `sdd/specs/auth-tenancy.md` — documenta el filtro global y las lecturas no scoped;
  recoge el guard de R6 como el sitio donde el invariante pasa a vivir.
- `sdd/specs/guest-portal-api.md`, `sdd/specs/auth-account-recovery.md` — cada una aporta
  una de las cuatro lecturas no scoped que pasan por el guard.
- `sdd/specs/cleaning.md` — además de lo anterior, es la spec de la ruta anónima de fotos
  cuyas dos copias corrige R5.

Fuera de `sdd/specs/`, este change modifica **`sdd/steering/security.md`** (la tabla de
la regla 11: fila de `notification_logs` completada y recuentos corregidos) y
`sdd/roadmap/user-management.md` + `sdd/roadmap/access-notifications.md`. Ninguno es una
spec, y los tres se tocan en el mismo diff.
