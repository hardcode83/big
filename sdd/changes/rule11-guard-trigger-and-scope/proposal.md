# Proposal: rule11-guard-trigger-and-scope

## Why

El guardián de la propiedad de los sumideros de la regla 11 —`backend/tests/test_rule11_ownership.py`,
que existe desde `rule11-ownership-single-source` (2026-08-18) porque «la prosa no se puede obligar a
estar al día»— **no se ejecuta en el commit que introduce el defecto, y sí en el siguiente que pase por
allí**. Su entrada y su gatillo son conjuntos disjuntos, y eso está medido, no inferido:

- **Qué lee**: `sdd/**`, `docs/**` y los `.py` de `backend/{app,alembic/versions,tests}` (`_prose_roots()`
  y `_code_files()`).
- **Qué lo dispara**: nada de eso. `backend-tests.yml:187` decide el área del diff con
  `case "$f" in backend/* | .github/workflows/backend-tests.yml)`, así que un commit de sola prosa
  —que es **exactamente** la forma de todo commit de `/sdd:archive`— no ejecuta la suite que contiene
  al guardián.

**La consecuencia ya ocurrió y sigue viva.** El archivado de `notification-writers-gap` (`f86a83f`,
2026-08-30) dejó tres bloques infractores en `sdd/specs/access-notifications.md`. En el run
33409418091 de `main`: `backend-tests-detect` success, `backend-tests` success,
**`backend-tests-suite` skipped**. `main` está verde en CI y rojo en local. Reproducido en este change
ejecutando la propia detección del guardián sobre el árbol de `origin/main@96756a0`: **3 infractores,
y ninguno más en todo el árbol**:

| Fichero | Línea | Frase que dispara el eje de propiedad |
|---|---|---|
| `sdd/specs/access-notifications.md` | 372 | `sin escritor` |
| `sdd/specs/access-notifications.md` | 525 | `tienen escritor` |
| `sdd/specs/access-notifications.md` | 689 | `sin escritor` |

Los tres son atribución de **miembros del enum `NotificationType`** en una spec viva, escritos por
`/sdd:archive`. No es prosa descuidada: es la forma que el archivado produce.

**Y muerde a quien no lo rompió**, que es lo que lo hace urgente y no meramente correcto: la PR de
`guest-portal-messaging` sí toca `backend/**`, así que sí ejecutaría la suite y saldría roja por tres
bloques que no ha escrito. Su `BLOCKED.md` paró el ship por eso, con decisión tomada con Jose el
2026-08-31: arreglar el guardián primero. Un guardián que reparte el coste al azar no protege.

**Es la segunda vez que este proyecto comete este error exacto, y la primera está escrita**:
`sdd/roadmap.md` dice, sobre la guardia de puertos, «**no puede vivir en `backend/tests/`**:
`backend-tests.yml:137` decide el área con `case "$f" in backend/* …`, así que un PR que solo toque
`docker-compose.yml` **no ejecutaría la suite** — justo el PR donde la guardia tendría que hablar». La
salida que allí se eligió existe y funciona: `.github/workflows/compose-ports.yml`, un job, sin
`paths:`, invocando un target de `make`.

Al mismo guardián se le midió un tercer defecto, del que este change sí se ocupa: su alcance de
ficheros no está fijado, así que **escanea `sdd/roadmap.md`**, y una entrada de roadmap que describe
trabajo pendiente («sus tres tipos no tienen escritor») disparó el eje de propiedad sin ser una
afirmación de censo. Eso forzó una edición de `sdd/roadmap.md` desde `guest-portal-messaging` que su
panel de review levantó **cuatro veces** como violación de la regla 1 del toolkit.

**Y ese defecto es más agudo de lo que estaba escrito, medido al redactar este proposal.** La entrada
de roadmap de *este* change disparó el guardián al escribirse, y el eje de sumideros no encajó por
ninguna columna del censo: encajó por su propio **meta-vocabulario**, `regla 11` y `censo`, que están en
`SINK_TERMS`. La consecuencia es estructural y no anecdótica: **cualquier documento que hable del censo
—una entrada de roadmap, una nota de análisis, este mismo tipo de texto— dispara el eje de sumideros
sin nombrar ni una columna**, así que basta una frase del eje de propiedad para que un texto *sobre* el
guardián resulte infractor. La entrada se reescribió para no usar el vocabulario, que es exactamente el
apaño que R2 viene a hacer innecesario.

Contexto: `sdd/steering/security.md` regla 11 y su sección «Sumideros de texto en claro» (la
autoridad); `sdd/changes/guest-portal-messaging/design.md` § Roadmap candidates (los tres defectos, y
de donde sale este change); `sdd/specs/backend-ci.md` (la prohibición de `paths:` en `on:`);
`sdd/specs/local-environment.md` (el precedente de `compose-ports`).

## What changes

Después de este change, el guardián de la regla 11 **se ejecuta en cualquier Pull Request cuyo diff
toque algo de lo que escanea**, desde un workflow propio de un solo job —sin `paths:` en `on:`, sin
Postgres, sin Redis y sin `.env`—, con su propio check run; su **alcance de ficheros es un dato
declarado** que dice, entrada por entrada, qué árbol es censo y cuál es prosa que puede citar la regla
sin reafirmarla, con `sdd/roadmap.md` y `sdd/roadmap/**` fuera y con el coste de esa exclusión medido y
escrito; y los tres bloques que hoy ponen `main` en rojo dejan de serlo **sin tocarlos** —nunca
fueron infractores: encajaban por el meta-vocabulario del censo y por ninguna columna, así que lo que
se corrige es el detector y no la prosa (enmienda OQ2, ver `design.md` § Open questions)—, así que el
guardián da verde sobre la base sin que ninguna de las tres afirmaciones se pierda ni se mueva. No se redefine el eje de
propiedad: sigue siendo la lista de trece redacciones que es hoy, y su hueco por paráfrasis sigue
declarado como residual.

## Requirements

### R1 — El guardián se dispara en el commit que introduce el defecto

**As a** persona que archiva un change (cuyo commit sólo toca prosa), **I want** que el guardián de la
regla 11 se ejecute en mi Pull Request, **so that** el rojo llegue a quien lo causa y no a la siguiente
feature que pase por `backend/**`.

Acceptance criteria:

1. WHEN el diff de un Pull Request toca cualquier ruta que el guardián escanea —`sdd/**`, `docs/**`,
   los `.py` de `backend/app/**`, `backend/alembic/versions/**` y `backend/tests/**`— o el propio
   guardián o su workflow, THE SYSTEM SHALL ejecutar el guardián y publicar su resultado como un check
   run propio, distinto del de `backend-tests`.
2. THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`**, prohibido por `sdd/specs/backend-ci.md`
   («un filtro de rutas a nivel de disparador no produce check alguno en los PR que no tocan esas
   rutas»): cualquier filtrado ocurre **dentro** del workflow.
3. WHERE el guardián se ejecuta en CI, THE SYSTEM SHALL no requerir Postgres, Redis, `.env` ni ningún
   secret — el guardián sólo lee ficheros del árbol, y el precedente de `api-contract.yml` y
   `compose-ports.yml` es dar señal en segundos.
4. IF cualquier paso de la cadena falla —descubrimiento de ficheros, parseo de un `.py`, alcance del
   árbol de prosa—, THEN THE SYSTEM SHALL terminar en rojo con mensaje propio, nunca en verde y nunca
   en `skip`. El centinela que ya existe (`test_the_prose_tree_is_actually_visible`) conserva su
   semántica: un árbol no alcanzable es rojo, porque `skip` se lee como «no aplica».
5. WHEN el guardián se ejecuta desde su superficie nueva, THE SYSTEM SHALL escanear el mismo conjunto
   de ficheros que escanea hoy desde `pytest`, verificado comparando el censo de infractores que
   producen las dos vías sobre el mismo árbol.

### R2 — El alcance del guardián es un dato, y el roadmap no es censo

**As a** quien escribe una entrada de roadmap describiendo trabajo pendiente, **I want** que el
guardián no me marque por nombrar una columna y decir que nadie la escribe todavía, **so that** no haya
que editar un fichero compartido para desbloquear una puerta de merge ajena.

Acceptance criteria:

1. WHEN el guardián decide qué ficheros recorre, THE SYSTEM SHALL derivarlo de una estructura de datos
   declarada que enumere, entrada por entrada y con su motivo escrito, qué árboles son **censo** (la
   autoridad y las specs vivas que la citan) y cuáles son **prosa fuera de censo**.
2. WHERE un fichero es `sdd/roadmap.md` o vive bajo `sdd/roadmap/**`, THE SYSTEM SHALL no reportarlo
   como infractor — con la excepción declarada que ya existe para
   `sdd/roadmap/rule11-ownership-single-source.md`, que deja de ser necesaria y debe desaparecer con
   ella.
3. WHEN se declara esa exclusión, THE SYSTEM SHALL registrar su **coste medido** —cuántos bloques del
   roadmap disparan hoy los dos ejes— en el sitio donde el guardián ya declara lo que no cubre
   (`test_what_this_guard_does_not_catch`), del mismo modo que la exclusión de `sdd/changes/` declara
   sus 36 bloques.
4. IF una entrada de la estructura de alcance —exclusión o excepción— deja de corresponder a una ruta
   que el escaneo recorre, THEN THE SYSTEM SHALL ponerse en rojo nombrando la entrada muerta, como ya
   hace `test_every_declared_exception_still_earns_its_place`.
5. WHEN el guardián reporta un infractor, THE SYSTEM SHALL seguir nombrando fichero, línea y la frase
   exacta que disparó cada eje.
6. WHEN un bloque encaje el eje de sumideros **sólo** por el meta-vocabulario del censo (`regla 11`,
   `censo`) y no por ninguna columna ni tabla censada, THE SYSTEM SHALL no reportarlo, o SHALL declarar
   por escrito por qué ese encaje cuenta — es lo que hace que un texto *sobre* el guardián sea
   infractor por hablar de él, y está medido en el § Why de este proposal.

### R3 — `main` vuelve a verde sin que ninguna afirmación se pierda

**As a** quien abre la siguiente PR que toque `backend/**`, **I want** que el guardián dé verde sobre
la base, **so that** el rojo que vea sea mío.

Acceptance criteria:

1. WHEN el guardián se ejecuta sobre la rama de este change fusionada con `main`, THE SYSTEM SHALL
   reportar **cero** infractores.
2. **Enmendado por OQ2 en el gate del 2026-08-31** (redacción original abajo). Los tres bloques de
   `sdd/specs/access-notifications.md` (372, 525 y 689) **no se corrigen, porque nunca fueron
   infractores**: encajan el eje de sumideros por el meta-vocabulario del censo (`censo`) y no por
   ninguna columna que la tabla gobierne — lo que atribuyen son miembros del enum
   `NotificationType`, cuya autoridad es otra. Así que THE SYSTEM SHALL dejarlos **intactos** y
   SHALL corregir el detector (R2.6), y no hay hecho que reubicar. *Redacción original, conservada
   para que la enmienda sea legible: «WHEN se corrigen los tres bloques …, THE SYSTEM SHALL
   conservar el hecho que cada uno transmite …, reubicándolo si su home correcto es otro, y no
   limitarse a borrarlo.» Suponía una reescritura que la medición volvió innecesaria.*
3. **No se ejerce** (OQ2). Se conserva porque su condición sigue siendo la correcta si alguna vez se
   cumple: IF la corrección exigiera declarar ese fichero como excepción en lugar de reescribirlo,
   THEN THE SYSTEM SHALL registrar el motivo en la entrada de la excepción, y no dejarlo implícito
   en el verde. Aquí no se declaró excepción alguna para ese fichero: se estrechó el eje.
4. WHERE el criterio en disputa sea la atribución de un **miembro de enum** frente a la de una
   **columna** —`R1.3` de `rule11-ownership-single-source` la puso en alcance a propósito, y el
   residual 8 del propio guardián dice que su eje de sumideros no puede verla—, THE SYSTEM SHALL dejar
   por escrito qué queda decidido, porque los tres bloques de `main` son exactamente ese caso.

### R4 — La forma nueva se demuestra en rojo antes de darse por buena

**As a** revisor, **I want** ver la guardia fallar por cada vía que dice cubrir, **so that** un verde
no signifique «no se ejecutó».

Acceptance criteria:

1. WHEN se verifica este change, THE SYSTEM SHALL demostrar la ejecución del guardián por **las dos**
   vías, con evidencia registrada: un diff que sólo toca prosa (`sdd/**` o `docs/**`) y un diff que
   sólo toca `backend/**`.
2. WHEN se introduce deliberadamente un bloque infractor de cada forma que el guardián dice cazar
   —atribución en markdown y atribución en un docstring o run de `#` de un `.py`—, THE SYSTEM SHALL
   ponerse en rojo en ambas, y la demostración SHALL quedar registrada en el change.
3. IF el guardián se ejecutara con su lista de rutas de alcance vacía o su árbol de prosa ausente,
   THEN THE SYSTEM SHALL fallar en alto y no reportar «cero infractores».

### R5 — La autoridad describe el guardián que existe

**As a** quien lee la regla 11 para saber qué le obliga, **I want** que su descripción del guardián
coincida con el código, **so that** la autoridad no envejezca en el mismo movimiento que la arregla.

Acceptance criteria:

1. WHEN este change altere el alcance o el gatillo del guardián, THE SYSTEM SHALL actualizar la
   sección «Sumideros de texto en claro (regla 11)» de `sdd/steering/security.md`, que hoy enumera qué
   recorre, qué excluye y sus dos excepciones declaradas.
2. THE SYSTEM SHALL no crear un segundo home para ese contrato: la sección de `steering/security.md`
   sigue siendo el único sitio donde vive, y el resto lo cita.
3. WHEN se enuncie cualquier recuento (bloques excluidos, excepciones, rutas en alcance), THE SYSTEM
   SHALL contarlo contra la fuente en el momento de escribirlo, no incrementar el número anterior —la
   propia sección de la regla 11 declara esa obligación sobre sus cuatro recuentos.

## Out of scope

- **Rediseñar el eje de propiedad para que deje de ser una lista de redacciones.**
  `OWNERSHIP_PATTERNS` son 13 patrones literales (8 en castellano, 5 en inglés) y el hueco está
  medido: el comentario que `guest-portal-messaging` añadió en
  `backend/app/messaging/application/portal.py:95-97` es exactamente la clase de prosa que el guardián
  existe para cazar y **no dispara**, por paráfrasis. Ya está declarado como residual 1 («Paraphrase»)
  del propio guardián. Fuera de aquí porque «qué forma exacta sustituye a la lista» es un problema
  abierto que pide su propio design, y este change tiene que aterrizar para desbloquear
  `guest-portal-messaging`. Va como candidato de roadmap.
- **Meter los miembros de `NotificationType` en el eje de sumideros** (residual 8). El propio guardián
  dice por qué se dejó sin hacer: hay muchos más que columnas, se renombran libremente, y un eje que
  los persiga sería la lista inmantenible que aquel change vino a abolir. Este change sólo decide qué
  hacer con los tres bloques vivos (R3.4), no cambia el eje.
- **La exclusión de `sdd/changes/`** y sus 36 bloques que disparan los dos ejes. Es una concesión
  medida y argumentada (un registro de change es el mismo documento antes y después del `mv`), y
  reabrirla no es lo que hoy está roto.
- **El residual de columna a pelo sin su tabla** (`docs/adr/0007-webhook-event-retry-columns.md:43`,
  residual 7).
- **Los demás gates de área de CI.** Que `backend-tests.yml` decida el área por paths es correcto para
  la suite del backend; lo que este change arregla es que un guardián que no lee `backend/**` dependa
  de ese gate. No se toca `frontend-tests.yml` ni ningún otro.
- **El canal de resultados del panel de revisión del toolkit** (el otro candidato de
  `guest-portal-messaging`): es deuda del toolkit, no de este árbol.

## Affected specs

**Actualizado tras el design y la review: de las dos specs que este apartado anticipaba, ninguna se
toca, y la que sí cambia es una nueva.** Se conserva el razonamiento original de cada una porque
explica por qué se esperaba tocarlas.

- `sdd/specs/rule11-ownership-guard.md` — **nueva, y el único cambio real en `sdd/specs/`**: es el
  home propio que D8 eligió para el mecanismo (gatillo, check run, fallo cerrado, vía local con su
  suelo de intérprete, y qué no cubre). Cita a `steering/security.md` y no reproduce el censo.
- `sdd/specs/access-notifications.md` — **citada, no modificada.** Se anticipaba «los tres bloques
  infractores (372, 525 y 689) que hoy ponen `main` en rojo», y la medición de OQ2 lo desmintió:
  nunca fueron infractores, encajaban por el meta-vocabulario y por ninguna columna del censo. R3.2
  quedó enmendado en consecuencia y el fichero **no aparece en el diff de este change**.
- `sdd/specs/backend-ci.md` — **citada, no modificada.** Aquí vive la prohibición de `paths:` que R1.2
  invoca, y este apartado dejaba abierto si el workflow nuevo se declaraba en ella o en un home
  propio. D8 resolvió lo segundo (precedente: `compose-ports` se declaró en
  `sdd/specs/local-environment.md`, porque su asunto era la postura del compose y no el CI), así que
  `backend-ci.md` se lee pero no se escribe.
- `sdd/specs/local-environment.md` — dos recuentos que el target nuevo falsea, y un tercero corregido
  al pasar, fuera de alcance y anotado como tal en el design.
- `sdd/specs/incident-photos.md` — una cita de la ruta vieja del guardián, en prosa y no funcional.

Fuera de `sdd/specs/`, este change modifica:

- **`sdd/steering/security.md`** — la sección de la regla 11 describe el alcance, las exclusiones y las
  dos excepciones declaradas del guardián (R5). Es la autoridad, no una spec.
- **`sdd/roadmap.md`** — la entrada ad-hoc de este change y la relación que declara que
  `guest-portal-messaging` lo necesita.
- `backend/tests/test_rule11_ownership.py`, un workflow nuevo en `.github/workflows/`, un target de
  `Makefile` y probablemente `scripts/` — implementación, no documento.
