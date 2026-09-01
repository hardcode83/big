# Design: rule11-guard-trigger-and-scope

## Context

El guardián vive hoy en `backend/tests/test_rule11_ownership.py` (497 líneas, sólo stdlib:
`ast`, `re`, `pathlib`). Escanea **969 ficheros** — 180 `.md` bajo `sdd/` y `docs/` y 789 `.py`
bajo `backend/{app,alembic/versions,tests}` (medido en este worktree el 2026-08-31) — y reporta
un bloque cuando encajan **dos ejes**: `SINK_TERMS` (21 términos) y `OWNERSHIP_PATTERNS` (13
redacciones literales). Su alcance no es un dato: está repartido entre `_prose_roots()`,
`_code_files()`, `EXCLUDED_DIRECTORIES` (2 entradas), `DECLARED_EXCEPTIONS` (2 entradas) y la
constante `AUTHORITY`.

Al vivir en `backend/tests/` depende de dos cosas que este change desmonta. La primera es el
gatillo: `backend-tests.yml:187` decide el área con
`case "$f" in backend/* | .github/workflows/backend-tests.yml)`, así que un commit de sola prosa
—la forma de todo commit de `/sdd:archive`— salta `backend-tests-suite`. La segunda es el
alcance del contenedor: `docker-compose.yml:121-122` monta `./sdd:/workspace/sdd:ro` y
`./docs:/workspace/docs:ro` **exclusivamente** para este fichero (verificado con un grep de
`/workspace/sdd` sobre `backend/`: los dos únicos aciertos están en este guardián), y de ahí
salen `_prose_roots()` con sus dos candidatos y el centinela
`test_the_prose_tree_is_actually_visible`, que existe porque un bind mount con origen ausente
lo crea Docker como directorio vacío.

La forma que este change tiene que copiar ya existe en el árbol y está escrita: `compose-ports`
—`scripts/compose-ports.py` + `scripts/test_compose_ports.py` + `make check-compose-ports` +
`.github/workflows/compose-ports.yml`, un job, sin `paths:`, y su spec en
`sdd/specs/local-environment.md`— nació de la misma frase («no puede vivir en
`backend/tests/`») que el § Why de este proposal cita como la primera vez que el proyecto
cometió este error. `api-contract.yml` es el otro precedente de workflow de un solo job.

La autoridad del contrato es `sdd/steering/security.md` § «Sumideros de texto en claro (regla
11)»: 21 columnas del censo en 28 filas, seis excepciones, y en su línea 126 la descripción del
guardián (qué recorre) y en la 128 sus exclusiones y sus dos excepciones declaradas.

## La medición que gobierna este diseño

Antes de decidir nada se midió qué aporta cada mitad de `SINK_TERMS`. Los 21 términos son dos
cosas distintas: **16 columnas y tablas del censo** (`audit_logs`, `messages.content`, …) y
**5 términos de meta-vocabulario** (`regla 11`, `rule 11`, `censo`, `sumidero de texto en
claro`, `cleartext sink`). El docstring del fichero justifica los primeros con una medición
sobre el árbol pre-barrido; los segundos entraron sin medirse.

Medido el 2026-08-31 sobre todo el corpus (969 ficheros **más** los árboles excluidos, para no
juzgar con la muestra recortada), contando bloques que encajan el eje de propiedad:

| Encaje del eje de sumideros | Bloques |
|---|---|
| Por una columna o tabla del censo | 47 |
| **Sólo** por meta-vocabulario | **16** |

De esos 16, catorce están en árboles excluidos (`sdd/changes/`) o en las dos excepciones
declaradas. **Los tres restantes son los tres infractores que hoy ponen `main` en rojo** —
`sdd/specs/access-notifications.md:372`, `:525` y `:689` — y **los tres encajan por la palabra
`censo` y por nada más**:

| Fichero | Línea | Término de sumidero que encaja | Qué dice el bloque |
|---|---|---|---|
| `sdd/specs/access-notifications.md` | 372 | `censo` | los trece miembros de `NotificationType` con escritor y los cuatro sin él |
| `sdd/specs/access-notifications.md` | 525 | `censo` | el decimoséptimo miembro del enum y su escalado |
| `sdd/specs/access-notifications.md` | 689 | `censo` | cuatro tipos siguen sin escritor, y el test de censo que los fija |

Es decir: **el meta-vocabulario no aporta ni un solo verdadero positivo dentro del alcance, y
aporta los tres falsos positivos que bloquean el ship de `guest-portal-messaging`**. Los tres
bloques no atribuyen ninguna columna del censo de la regla 11 — atribuyen **miembros del enum
`NotificationType`**, cuya autoridad es otra (`backend/tests/notifications/test_writer_census.py`,
que el propio bloque 689 cita). El guardián los cazaba por hablar de *un censo*, no por
duplicar *el* censo. Eso es exactamente la patología que R2.6 describe.

> **Esta medición es del 2026-08-31 y son tres porque entonces eran tres.** Recontada sobre el
> árbol que se entrega (2026-09-01) son **cuatro**: el que se ha sumado es
> `sdd/specs/rule11-ownership-guard.md:11`, el párrafo de la spec que D8 crea y que declara que el
> contrato no vive allí. Es falso positivo como los otros tres y no mueve ninguna conclusión de
> este diseño, pero deja claro que la spec nueva da verde gracias al estrechamiento que hace este
> mismo change. La cifra viva vive en `scripts/rule11-ownership.py` y en la spec, no aquí.

Y la consecuencia es la que ordena el resto del diseño: **R2.6 hecho bien resuelve R3.1 sin
editar una sola línea de `sdd/specs/access-notifications.md`.** Verificado: con el eje de
sumideros reducido a columnas y tablas, los infractores en alcance pasan de 3 a **0**, y los
cuatro casos positivos de `test_the_scan_catches_what_it_claims_to` siguen encajando los dos
—todos nombran una columna real del censo.

## Decisions

### D1 — El guardián se muda a `scripts/`, y no se queda en `backend/tests/` con un workflow más gordo

**Chosen:** `backend/tests/test_rule11_ownership.py` se borra. La lógica pasa a
`scripts/rule11-ownership.py` (guardia ejecutable con `main() -> int`, la forma exacta de
`compose-ports.py`) y las meta-pruebas a `scripts/test_rule11_ownership.py` (cargando el módulo
con `importlib.util.spec_from_file_location`, la forma exacta de `test_compose_ports.py`). Se
invoca con `make check-rule11-ownership` y desde `.github/workflows/rule11-ownership.yml`.

Es lo que la entrada de `compose-ports-guard` ya dictaminó para una guardia de esta clase, y
resuelve las dos dependencias del § Context a la vez: el gatillo (D2) y el alcance del
contenedor. Concretamente **borra** maquinaria en vez de añadirla: `_prose_roots()` deja de
tener dos candidatos, el bind mount de `./sdd` y `./docs` desaparece (D9) y no hace falta ni
`uv sync --frozen`, ni el `JWT_SECRET_KEY` y el `ENCRYPTION_KEY` de usar y tirar que
`api-contract.yml` genera, ni sortear `backend/tests/conftest.py` — que importa `asyncpg`,
SQLAlchemy y `app.core.config`, y por tanto arrastraría el árbol de dependencias entero del
backend para un escaneo de texto de stdlib. R1.3 pide justo eso.

Rejected:
- **Quedarse en `backend/tests/` y que el workflow nuevo invoque `pytest` sobre ese fichero** —
  funciona (es la forma de `api-contract.yml`), pero paga `uv sync --frozen` y dos claves
  falsas para un escáner de stdlib, y conserva el candidato `/workspace/` y su centinela de
  mount, que es complejidad cuya única causa es vivir dentro del contenedor.
- **Las dos superficies a la vez** (script en `scripts/` y un test del backend que lo importe) —
  imposible sin *añadir* un tercer bind mount (`./scripts:/workspace/scripts:ro`), es decir
  crecer la maquinaria que D1 existe para retirar; y convierte la comparación puntual de R1.5 en
  una obligación permanente de dos caminos.

**El coste, dicho entero:** el `pytest` del backend deja de ejecutar el guardián, así que quien
escriba un docstring infractor en `backend/app/**` ya no lo ve en su suite local. La mitigación
es que la vía local pasa a ser **más barata que hoy**, no más cara: `make check-rule11-ownership`
corre con el `python3` del host en un segundo, sin Docker, sin stack levantado y sin el
`make down && make up` que hoy exige el centinela del mount. Se documenta en la spec nueva (D8)
y en `sdd/project.md`.

### D2 — El workflow no lleva gate de área: se ejecuta siempre

**Chosen:** `rule11-ownership.yml` con `on: pull_request: {}` + `push: branches: [main]` +
`workflow_dispatch: {}`, **sin `paths:`** (R1.2), un solo job llamado `rule11-ownership` — el
nombre del check run sale del *job*, no del workflow — y **ninguna detección de área dentro**.

R1.1 pide que el guardián corra cuando el diff toque cualquier ruta que escanea; correr siempre
lo satisface trivialmente y por construcción. Y es lo correcto aquí por un motivo que no es
sólo comodidad: un gate de área es **un segundo sitio donde equivocarse sobre el alcance**, que
es literalmente el defecto que este change arregla. El escaneo tarda ~1 s sobre 969 ficheros, así
que los tres jobs de `backend-tests.yml` no se pagan — el mismo razonamiento que
`api-contract.yml` y `compose-ports.yml` escriben en su cabecera.

`push: branches: [main]` no es decorativo: es lo que habría puesto en rojo el run 33409418091,
donde `backend-tests-suite` salió `skipped` sobre el commit `f86a83f` que introdujo los tres
bloques.

Rejected: **copiar el patrón detect/suite/publish de `backend-tests.yml`** — su complejidad
existe para no pagar 20 minutos de Postgres y Redis; aquí no hay nada que ahorrar.

### D3 — El eje de sumideros pierde el meta-vocabulario, y el motivo es la medición

**Chosen:** `SINK_TERMS` queda con las **16 columnas y tablas del censo**. Los 5 términos de
meta-vocabulario (`regla 11`, `rule 11`, `censo`, `sumidero de texto en claro`, `cleartext
sink`) salen del eje. Con eso, un bloque se reporta sólo si nombra **algo que la tabla de la
regla 11 gobierna**, que es lo que el eje decía ser.

La medición del § anterior es el argumento entero: **cero verdaderos positivos en alcance** y sólo
falsos —cuántos, lo dice esa medición con su fecha y lo afirma
`test_the_declared_cost_of_dropping_the_meta_vocabulary_is_still_what_the_prose_says`; aquí no se
repite el numeral a propósito, porque es así como esta cifra se quedó obsoleta dos veces—, y `main`
pasa de 3 infractores a 0 (ése sí es firme: son los tres bloques que el eje viejo reportaba de
verdad). Cumple R2.6 por su primera rama («SHALL no
reportarlo») en vez de por la segunda («declarar por qué ese encaje cuenta»), porque la segunda
no se puede defender: un texto *sobre* el guardián resultando infractor por hablar de él no es
una atribución duplicada de nada.

**Lo que esto pierde, y va como residual declarado:** una atribución que nombre la columna
**por referencia** sin nombrarla («la única columna que este change hereda como primer
escritor») deja de encajar. La forma existe — `sdd/changes/archive/2026-08-08-access-notifications/design.md:169`
la tiene — pero vive en un árbol excluido, así que el coste **medido hoy es cero bloques en
alcance**. Entra como residual nuevo en `test_what_this_guard_does_not_catch`.

Rejected:
- **Dejar el meta-vocabulario y exceptuar `sdd/specs/access-notifications.md`** — compra el
  verde regalando un fichero de 55 KB al que el guardián dejaría de mirar entero, y por un
  encaje que era espurio. Es R3.3 y está disponible, pero es la peor de las salidas.
- **Distinguir por escrito si la frase de propiedad gobierna un miembro de enum o una columna** —
  es el análisis semántico que el propio guardián declara no hacer («the axis is a vocabulary,
  not a semantic analyser»), y sería la lista inmantenible que su change fundacional vino a
  abolir.
- **Exigir que el meta-vocabulario co-ocurra con un término del censo** — matemáticamente igual
  a quitarlo, con más código.

### D4 — El alcance pasa a ser una sola estructura de datos, y el escaneo se deriva de ella

**Chosen:** una tupla `SCOPE` de entradas inmutables, cada una con `path`, `kind` y `reason`
obligatorio y no vacío:

```python
class Kind(StrEnum):
    AUTHORITY = "authority"        # la tabla: el único home de la propiedad
    CENSUS_PROSE = "census-prose"  # árboles de prosa que citan la autoridad
    CENSUS_CODE = "census-code"    # árboles de código cuyos docstrings la citan
    OUT_OF_CENSUS = "out-of-census"  # prosa que puede citar la regla sin reafirmarla
    EXCEPTION = "exception"        # un fichero concreto que lleva los dos ejes con motivo

@dataclass(frozen=True)
class ScopeEntry:
    path: str
    kind: Kind
    reason: str
```

`_prose_files()` y `_code_files()` dejan de tener rutas literales y se derivan de `SCOPE`;
`EXCLUDED_DIRECTORIES` y `DECLARED_EXCEPTIONS` desaparecen como estructuras separadas y pasan a
ser vistas filtradas de `SCOPE`. Cumple R2.1: entrada por entrada, con su motivo escrito, qué
árbol es censo y cuál es prosa fuera de censo.

El motivo no es estética. La memoria de este proyecto ya lo tiene escrito para los guardianes
AST: *fijar la forma exacta y los ficheros en alcance*, porque un guardián cuyo alcance vive
repartido en cinco sitios es un guardián cuyo alcance nadie puede auditar de una lectura — y
el defecto que este change arregla es precisamente que su alcance y su gatillo eran conjuntos
disjuntos sin que ninguna estructura lo dijera.

Rejected: **mantener las cinco estructuras y añadir sólo `reason` a las exclusiones** — deja el
alcance sin un sitio donde leerlo entero, que es lo que R2.1 pide.

### D5 — `sdd/roadmap.md` y `sdd/roadmap/**` salen por exclusión declarada, y la excepción nombrada muere

**Chosen:** dos entradas `OUT_OF_CENSUS` en `SCOPE` — `sdd/roadmap.md` y `sdd/roadmap` — y se
**borra** la entrada `sdd/roadmap/rule11-ownership-single-source.md` de las excepciones (R2.2 lo
manda, y `test_every_declared_exception_still_earns_its_place` lo exigiría de todos modos:
medido, bajo D3 ese fichero deja de producir bloque alguno, así que su entrada quedaría muerta).

**Coste medido, que es lo que R2.3 pide registrar:** bloques del árbol del roadmap que encajan
los dos ejes, **hoy y bajo D3: 0**. (Con el eje actual era 1, y era el fichero ya exceptuado por
nombre.) Se escribe en `test_what_this_guard_does_not_catch` junto a la cifra de
`sdd/changes/`, del mismo modo que ésa declara la suya.

Con coste cero cabe preguntarse si la exclusión gana su sitio, y lo gana por una razón
estructural que no depende de D3: **una entrada de roadmap es una declaración de trabajo no
hecho**, y decir «esta columna todavía no tiene escritor» es su función, no una reafirmación del
censo — el mismo argumento que sostiene la exclusión de `sdd/changes/` (un registro de change es
el mismo documento antes y después del `mv`). Sin ella, si alguien ensanchara el eje en el
futuro, el roadmap volvería a forzar la edición de un fichero compartido para desbloquear una
puerta de merge ajena, que es lo que el panel de `guest-portal-messaging` levantó cuatro veces
como violación de la regla 1 del toolkit. Con ella, el roadmap queda fuera del censo por
construcción.

Rejected: **no excluir el roadmap y confiar en D3** — deja el arreglo colgando de una decisión
de vocabulario en vez de de una de alcance, y R2.2 lo pide como `SHALL`.

### D6 — Los tres bloques de `sdd/specs/access-notifications.md` no se tocan

**Chosen:** las líneas 372, 525 y 689 se quedan **exactamente como están**. Bajo D3 no son
infractores, y no lo son porque nunca atribuyeron una columna del censo de la regla 11: censan
miembros del enum `NotificationType`, cuyo home es esa spec más
`backend/tests/notifications/test_writer_census.py`. R3.1 se cumple con cero ediciones de prosa
y R3.2 se cumple de la única forma que no pierde nada: no reubicando un hecho que ya está en su
sitio.

**Y esto es lo que R3.4 manda dejar por escrito**, así que se escribe aquí y en la spec nueva:
la atribución de un **miembro de enum** no es una atribución de un **sumidero** para este
guardián. R1.3 de `rule11-ownership-single-source` puso la atribución de miembros de enum en
alcance de *la regla* a propósito, y el residual 8 del propio guardián ya declaraba que su eje
de sumideros **no puede verla**. Los tres bloques de `main` no eran ese caso resuelto: eran ese
caso *cazado por accidente*, a través de una palabra (`censo`) que habla del mecanismo y no de
ninguna columna. D3 no estrecha la regla: alinea la conducta del guardián con lo que su residual
8 ya decía de él. El residual 8 se queda, con esa aclaración añadida, y el ensanche del eje a
miembros de enum sigue fuera de alcance por los motivos que el proposal enumera.

Rejected:
- **Reescribir los tres bloques para que no digan «censo»** — pide a la prosa que esquive un
  detector defectuoso, que es el apaño que R2 viene a hacer innecesario (y es lo que ya se hizo
  con la entrada de roadmap de este change).
- **Declarar el fichero como excepción (R3.3)** — ver D3, rechazada por lo mismo.

### D7 — El fallo cerrado se traduce de `AssertionError` a código de salida con mensaje propio

**Chosen:** la guardia gana una `GuardError` (la forma de `compose-ports.py`) y un `main()` que
imprime `error: …` en `stderr` y devuelve `1`. Los tres puntos que hoy fallan cerrado se
conservan uno a uno (R1.4):

| Fallo | Hoy | Después |
|---|---|---|
| Árbol de prosa no alcanzable | `assert roots` en el centinela | `GuardError` + salida ≠ 0 |
| `SyntaxError` en un `.py` del alcance | `raise AssertionError` en `_python_blocks` | `GuardError` nombrando fichero y error |
| Menos de `MINIMUM_MARKDOWN_FILES` visibles | `assert scanned >= 40` | `GuardError` con la cifra vista |
| `SCOPE` vacía o una entrada `CENSUS_*` que no resuelve | *no existe* | `GuardError` (R4.3) |

El centinela **no puede convertirse en `skip`** por el motivo que su docstring ya escribe: en
salida `-rs` un `skip` se lee como «no aplica», que es lo peor que puede decir un control de
seguridad cuando su entrada ha desaparecido. Su mensaje cambia (deja de hablar de
`make down && make up`, que ya no aplica) y pasa a hablar de checkout incompleto.

### D8 — La spec vive en un home propio, no dentro de `backend-ci.md`

**Chosen:** `sdd/specs/rule11-ownership-guard.md` — nueva. El proposal delegó esta elección en
design (§ Affected specs).

`sdd/specs/backend-ci.md` tiene su Purpose acotado a «migraciones, coherencia esquema↔modelos y
la suite completa del backend», y ya explica que `api-contract` **vive aparte** por no necesitar
PostgreSQL ni Redis. Este guardián está en esa misma familia y, tras D1, ni siquiera vive bajo
`backend/`. El precedente de forma es `api-contract`, que tiene su propia spec; el precedente de
*criterio* es `compose-ports`, que se declaró en `local-environment.md` porque su asunto era la
postura del compose y no el CI — y aquí el asunto es el guardián de la regla 11, que no es el
asunto de ninguna spec existente.

**El límite con R5.2, que es la parte delicada:** la spec nueva describe el **mecanismo**
(gatillo, check run, fallo cerrado, dónde vive el alcance, la vía local) y **no reproduce el
contrato**: ni el censo de columnas, ni las excepciones de la regla, ni la enumeración de qué
árboles son censo. Para el contrato cita `sdd/steering/security.md` § regla 11; para el alcance
cita `SCOPE` como la fuente. Ese es el criterio operativo: **la spec no contiene ninguna lista
que `SCOPE` o la tabla ya contengan.**

Rejected:
- **`sdd/specs/backend-ci.md`** — mete un escáner de prosa de stdlib en la spec de la suite del
  backend, justo cuando el change lo saca de ahí.
- **Sólo `steering/security.md`** — steering no es una spec, y el gatillo y el check run son
  comportamiento del sistema que `sdd/specs/` debe documentar.

### D9 — Los dos bind mounts de `./sdd` y `./docs` se retiran de `docker-compose.yml`

**Chosen:** se borran las líneas 121-122 y su comentario. Verificado que el guardián es su único
consumidor (los dos únicos aciertos de `/workspace/sdd` en `backend/` están en el propio
fichero que D1 borra), así que dejarlas sería alcance muerto con un comentario que nombra un
fichero inexistente. Los otros **tres** montajes de `/workspace/` (`deploy-dev.yml`,
`demo-reset.yml`, `.env.example`) tienen consumidores vivos y **no se tocan**. *(Decía «cuatro» y
son tres: contados en `docker-compose.yml` al implementar, había cinco montajes de `/workspace/` y
quedan tres. Lo levantó el panel de la sección 4.)*

Beneficio lateral que conviene decir porque el comentario que se borra lo planteaba como coste
aceptado: el contenedor `backend` —que publica 8000 en todas las interfaces en dev— deja de
tener el árbol `sdd/` legible, es decir el modelo de amenazas interno del proyecto. Es una
reducción pequeña y real de su superficie de lectura.

### D10 — La demostración en rojo de R4 se hace sobre la superficie nueva, no sobre la función

**Chosen:** las meta-pruebas ya demuestran que la *función* detecta las dos formas
(`test_the_scan_catches_what_it_claims_to` cubre markdown, docstring y tirada de `#`), así que
lo que R4 aporta de nuevo es probar que **el check run** se pone rojo. El plan:

1. **R4.1 — las dos formas de diff.** Los dos runs se toman de **eventos `pull_request` sobre la
   PR ya abierta**, uno por cada forma de diff (sólo prosa y sólo `backend/**`), y se registran
   sus ids en `tasks.md`.

   > **Corregido en review (2026-09-01), y era un error de este design y no del `tasks.md`.**
   > Este paso decía «basta un push a la rama … la rama de este change produce los dos de forma
   > natural». Es falso, y lo contradice el propio D2: con `on: pull_request: {}` + `push:
   > branches: [main]`, un push a la rama de la feature **no produce ningún run** —no hay PR y la
   > rama no es `main`—, así que los ids no existen hasta que `/sdd:ship` abre la PR. Tampoco lo
   > salva `workflow_dispatch`: GitHub sólo ofrece despachar un workflow que ya existe en la rama
   > por defecto, y éste todavía no está en `main`. Se consideró ensanchar el `push:` a todas las
   > ramas para que la evidencia naciera antes; se descarta porque añadiría un run por cada push
   > de cualquier rama y porque el evento que R1.1 nombra es la Pull Request, así que el
   > `pull_request` es además la evidencia **mejor**, no sólo la disponible. Consecuencia
   > aceptada: **la sección 6 se ejecuta después de `/sdd:ship`**, no durante `/sdd:run`.

2. **R4.2 — rojo por cada forma.** Dos mitades, y conviene no confundirlas porque una no descarga
   la otra:
   - **El binario**, en local, sobre un bloque infractor inyectado de cada forma que la guardia
     dice cazar (markdown, docstring y tirada de `#`). No necesita PR: se hace con
     `make check-rule11-ownership` y se pega su salida en `tasks.md`.
   - **El check run**, en rojo sobre la PR, con su id, mediante un commit temporal revertido acto
     seguido.

   Y ninguna de las dos se descarga con el fallo cerrado: las ocho vías de `GuardError` son
   evidencia de **R1.4 y R4.3** —cadena rota—, no de R4.2, que es un bloque infractor recorriendo
   `offenders()` → `render()` → salida 1. Son caminos de código distintos.
3. **R4.3 — alcance vacío.** Meta-prueba: se construye una `SCOPE` vacía y se afirma que la
   guardia levanta `GuardError` en vez de reportar cero infractores; igual con un árbol de prosa
   ausente.

Rejected: **darlo por demostrado con las meta-pruebas** — probaría la función y no la
superficie, que es justo la distinción que este change existe para no volver a confundir.

> **Dónde vive cada mitad, resuelto en review el 2026-09-01 y esta vez por un gate, no por lectura.**
> Los pasos 1 y 2-check-run se escribieron como tareas de `tasks.md` y chocaron con **dos** gates
> independientes: el de ship rechaza un `BLOCKED.md` no vacío, y `mark-local-verified` rechaza
> cualquier tarea sin marcar. Como su evidencia no puede existir antes de que haya PR, una lista
> pre-PR nunca podría completarse y el change quedaba incertificable por construcción. Así que se
> reparte: lo que se demuestra en local —el binario en rojo por las tres formas— es la tarea 6.2a y
> está cerrada; lo del **check run** pasa a `sdd/specs/rule11-ownership-guard.md`
> § Obligaciones sobre la Pull Request abierta, antes del merge, como obligación declarada de la
> capacidad —**toda ella anterior al merge**—, con su acta en el § «Registro de evidencia sobre la
> PR» del `tasks.md`, y se ancla con `mark-recertified` sobre la PR abierta. D10 no cambia de criterio —la superficie sigue teniendo que demostrarse y las
> meta-pruebas siguen sin bastar—, cambia de dónde se registra.

### D11 — La prosa de la regla 11 queda anclada a `SCOPE` por una prueba

**Chosen:** una prueba mínima en `scripts/test_rule11_ownership.py` que lee la sección
«Sumideros de texto en claro (regla 11)» de `sdd/steering/security.md` y afirma, en las dos
direcciones, que **toda ruta que su frase de alcance nombra está en `SCOPE`** y **toda entrada
de `SCOPE` está nombrada en esa frase**. Resuelto en el gate del 2026-08-31 (OQ4 aceptada), así
que es alcance de este change y no una sugerencia.

El motivo es la tesis del propio guardián aplicada a sí mismo: R5 pide que la autoridad no
envejezca en el mismo movimiento que la arregla, y en este proyecto los recuentos de esa misma
sección ya envejecieron cuatro veces —«las dieciséis» cuando eran veintiuna, «cuatro
excepciones» cuando eran cinco— sin que nada se pusiera rojo. La obligación de recuento de R5.3
es prosa sobre prosa; esto es el test rojo.

**Forma mínima, y el límite escrito:** ancla **rutas**, no cifras y no motivos. No intenta
verificar que la `reason` de cada entrada coincida con lo que la prosa dice de ella —eso es
análisis semántico— ni recontar columnas ni excepciones. Y ancla una **frase acotada**, no la
sección entera, para que reescribir un párrafo de contexto no ponga en rojo un guardián de
alcance.

Riesgo aceptado y su mitigación: parsear prosa es frágil. La sección se localiza por su
encabezado literal y la frase de alcance por un marcador estable; si el parseo no encuentra el
marcador, la prueba **falla en alto nombrando el marcador ausente** (nunca pasa en vacío), que
es la misma postura de fallo cerrado de D7.

Rejected:
- **Sólo la obligación de recuento de R5.3** — es lo que R5 pide literalmente y es exactamente
  lo que ya falló cuatro veces en esta sección.
- **Anclar la sección entera, cifras incluidas** — convierte cada edición de prosa en un rojo y
  el guardián en algo que se desactiva.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Guardia | `scripts/rule11-ownership.py` | **Nuevo.** La lógica de `backend/tests/test_rule11_ownership.py` con `SCOPE` (D4), `SINK_TERMS` sin meta-vocabulario (D3), `GuardError` + `main() -> int` (D7) y `_prose_roots()` con un único origen (D1) |
| Guardia | `scripts/test_rule11_ownership.py` | **Nuevo.** Las cuatro pruebas de hoy más las de `SCOPE` (R2.4), la de alcance vacío (R4.3), el ancla prosa↔`SCOPE` (D11) y las cifras re-medidas de `test_what_this_guard_does_not_catch` |
| Guardia | `backend/tests/test_rule11_ownership.py` | **Se borra** (D1) |
| CI | `.github/workflows/rule11-ownership.yml` | **Nuevo.** Un job `rule11-ownership`, sin `paths:`, `contents: read`, `concurrency` con `cancel-in-progress`, `timeout-minutes: 10`; pasos: checkout, `setup-uv`, `make check-rule11-ownership`, `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/test_rule11_ownership.py -q` |
| CI | `.github/workflows/compose-ports.yml` | **Sin cambios**, y consta: su paso `pytest scripts/ -q` recogerá también las meta-pruebas nuevas. Se deja así porque ya es el statu quo para los otros cuatro `scripts/test_*.py`, y estrechar el glob crearía una lista que el próximo script hay que acordarse de ampliar |
| Local | `Makefile` | Target `check-rule11-ownership: python3 scripts/rule11-ownership.py`, junto a `check-compose-ports` y `check-version-parity`. **Fuera de `$(COMPOSE)`**, como sus dos hermanos |
| Local | `docker-compose.yml` | Se retiran `./sdd:/workspace/sdd:ro` y `./docs:/workspace/docs:ro` con su comentario (D9) |
| Spec | `sdd/specs/rule11-ownership-guard.md` | **Nueva** (D8): gatillo, check run, fallo cerrado, vía local, estado del check, y la decisión de D6 sobre miembro de enum vs columna |
| Autoridad | `sdd/steering/security.md` | § regla 11: la línea 126 (qué recorre) y la 128 (qué excluye, sus excepciones) se reescriben contra `SCOPE`; se nombra el check run y se cita la spec nueva. **Los cuatro recuentos de la cabecera se recuentan contra la tabla** (R5.3) |
| Docs | `sdd/project.md` | La vía local `make check-rule11-ownership` en § Commands |
| Refs | `sdd/specs/incident-photos.md`, `backend/tests/cli/test_demo_reset.py` (×2), `backend/tests/notifications/test_writer_census.py` | Cuatro citas de la ruta vieja, todas en prosa y ninguna funcional: apuntan al nuevo camino. Los archivos bajo `sdd/changes/archive/` **no se tocan** (inmutables) |
| Specs | `sdd/specs/local-environment.md` | Dos recuentos que el target nuevo falsea (tarea 4.4). **Y un tercero fuera de alcance**, aceptado: la frase de las tareas periódicas decía ocho y son nueve. No lo pide ningún R# ni D# —el change no falsea ese número—, se corrigió al pasar por allí y se recontó contra `backend/app/scheduler/schedule.py` (`CADENCES` 8 + `DAILY_JOBS` 1); queda anotado aquí para que ningún fichero del diff quede sin referente |
| Roadmap | `sdd/roadmap.md` | **Sólo la entrada de registro de `/sdd:new`** (la del propio change y el `needs:` que declara que `guest-portal-messaging` lo necesita). Ningún estado derivado: la regla 1 del toolkit reserva a `/sdd:archive` el tick y todo lo que `/sdd:status` deduce. **Corregido en review (2026-09-01)**: esta fila decía «no lo toca este change», y el diff lo toca — el registro entró dentro del commit de implementación `d05cca6` en vez de quedarse en el de bootstrap, que es lo que hizo la afirmación falsa |

## Data & interfaces

Sin esquema, sin migración, sin endpoint, sin variable de entorno, sin string de UI, sin
`openapi.json`. El contrato nuevo es interno al guardián y son tres piezas:

- **`SCOPE: tuple[ScopeEntry, ...]`** — el alcance como dato (D4). Fuente única de qué se
  recorre, qué se excluye y qué se exceptúa.
- **Salida de la guardia** — código `0` sin hallazgos; `1` con hallazgos o con `GuardError`. Cada
  hallazgo imprime **fichero, línea y la frase exacta que disparó el eje** (R2.5, conducta que
  se conserva literal).
- **Check run `rule11-ownership`** — nombre tomado del job. **Estado**: mientras el repositorio
  no tenga protección de rama compatible se ejecuta y reporta **sin** ser obligatorio para
  fusionar, igual que `api-contract`, `compose-ports` y `frontend-tests` y por el mismo motivo de
  plan de GitHub; el día que haya protección, entra en el conjunto de obligatorios.

## Cobertura de requisitos

| AC | Dónde queda |
|---|---|
| R1.1 | D2 — sin `paths:` y sin gate, corre en todo PR; check run propio, distinto de `backend-tests` |
| R1.2 | D2 — `on: pull_request: {}`; el filtrado no existe, así que no puede estar en el disparador |
| R1.3 | D1 — stdlib + `python3` del runner; ni Postgres, ni Redis, ni `.env`, ni secret |
| R1.4 | D7 — la tabla de los cuatro fallos cerrados; el centinela nunca es `skip` |
| R1.5 | D1 + verificación: el censo de infractores de la vía nueva se compara con el de `pytest` sobre el mismo árbol antes de borrar el fichero viejo. Bajo D3 la comparación es **0 = 0**, así que se hace también con el eje sin tocar (**3 = 3**) para que la igualdad pruebe la mudanza y no el cambio de eje |
| R2.1 | D4 — `SCOPE` con `path`/`kind`/`reason` |
| R2.2 | D5 — dos entradas `OUT_OF_CENSUS`; la excepción nombrada se borra |
| R2.3 | D5 — coste medido **0 bloques**, escrito en `test_what_this_guard_does_not_catch` |
| R2.4 | D4 — prueba nueva: toda entrada de `SCOPE` resuelve a una ruta que el escaneo recorre, y toda `reason` es no vacía |
| R2.5 | Conducta conservada literal; § Data & interfaces |
| R2.6 | D3 — primera rama: no se reporta |
| R3.1 | D3 + D6 — medido: 0 infractores en alcance |
| R3.2 | D6 — no se pierde nada porque no se mueve nada |
| R3.3 | No se ejerce; D3 y D6 explican por qué se rechazó |
| R3.4 | D6 — la decisión escrita, en el design y en la spec nueva; el residual 8 se queda, aclarado |
| R4.1 · R4.2 · R4.3 | D10 |
| R5.1 | § Changes by area — `steering/security.md` líneas 126 y 128; **anclado por prueba** (D11) |
| R5.2 | D8 — el criterio operativo: la spec nueva no contiene ninguna lista que `SCOPE` o la tabla ya contengan |
| R5.3 | § Changes by area; y el hallazgo del § Riesgos sobre el «36» del residual 5. D11 ancla las rutas; los recuentos siguen siendo obligación de recuento y no de test |

## Risks & mitigations

- **La cifra del residual 5 está desfasada, y se descubrió al medir.** Dice «`sdd/changes/`
  holds **36 blocks that fire both axes**»; medido el 2026-08-31 son **49** con el eje actual y
  **38** con el de D3. Mitigación: se recuenta contra la fuente al escribirlo, no se incrementa
  —la obligación que R5.3 impone a la cabecera de la regla 11 vale igual aquí—, y se re-mide en
  el momento de implementar, porque el número depende del árbol.
- **El `pytest` del backend pierde el guardián** (coste declarado en D1). Mitigación: la vía
  local pasa a ser más barata que hoy y se documenta en dos sitios (spec nueva y
  `sdd/project.md`). Riesgo residual aceptado: un docstring infractor se ve en CI y no en la
  suite local.
- **D3 abre un hueco real**: la atribución por referencia sin nombrar la columna. Mitigación:
  entra como residual declarado, con su ejemplo medido y la nota de que hoy no cuesta ningún
  bloque en alcance.
- **La spec nueva y `steering/security.md` pueden divergir** — es exactamente lo que R5 teme.
  Mitigación por criterio (D8: la spec no reproduce ninguna lista) y por prueba (D11, que ancla
  las rutas de la frase de alcance a `SCOPE` en las dos direcciones).
- **El ancla de D11 es un parseo de prosa**, y por tanto frágil. Mitigación: ancla rutas y no
  cifras, se limita a una frase acotada por un marcador estable, y falla en alto nombrando el
  marcador si no lo encuentra — nunca pasa en vacío.
- **Un `SCOPE` mal escrito da verde en vacío.** Es el fallo peor de todos porque es silencioso.
  Mitigación: R4.3 (`GuardError` con `SCOPE` vacía) + R2.4 (toda entrada resuelve) + el
  centinela de `MINIMUM_MARKDOWN_FILES`, que se conserva.
- **La mudanza podría cambiar el conjunto escaneado sin que nadie lo note.** Mitigación: R1.5 se
  verifica **dos veces**, con el eje viejo (3 = 3) y con el nuevo (0 = 0), y la primera es la
  que prueba que la mudanza no movió el alcance.
- **`origin/main` se mueve mientras esto está en vuelo.** El verde de R3.1 es sobre la rama
  fusionada con `main`, no sobre la rama sola: se mide después del merge de base en `/sdd:ship`.

## Open questions

**Ninguna abierta.** Las cinco se resolvieron con Jose en el gate del 2026-08-31, todas por la
opción recomendada. Se conservan aquí con su resolución porque tres de ellas enmiendan la
lectura literal de un requisito, y eso tiene que viajar al `tasks.md` y a la spec:

| OQ | Resolución | Dónde vive |
|---|---|---|
| **OQ1** — ¿el guardián sale del `pytest` del backend? | **Sí**, a `scripts/`. La alternativa (quedarse y pagar `uv sync` más dos claves falsas para un escáner de stdlib) queda rechazada por escrito | D1 |
| **OQ2** — ¿se tocan los tres bloques de `access-notifications.md`? | **No.** Nunca fueron infractores: encajan por `censo` y por ninguna columna del censo. **Enmienda a R3.2**, que estaba redactado suponiendo una reescritura y una reubicación: no hay hecho que reubicar. **R3.3 no se ejerce** | D6 |
| **OQ3** — ¿se mantiene la exclusión del roadmap con coste medido 0? | **Sí.** R2.2 la pide como `SHALL`, y la razón estructural (una entrada de roadmap declara trabajo no hecho) no depende de D3 | D5 |
| **OQ4** — ¿una prueba que ancle la prosa de la regla 11 a `SCOPE`? | **Sí, en su forma mínima.** Pasa a ser **alcance de este change**, más allá de R5 tal como está escrito: ancla rutas en las dos direcciones, no cifras ni motivos | **D11** (nueva) |
| **OQ5** — ¿home de la spec? | **Spec propia** `sdd/specs/rule11-ownership-guard.md`. Tras D1 el guardián no vive bajo `backend/` | D8 |

Lo que `/sdd:tasks` tiene que llevarse de aquí, porque no se deduce de los requisitos:

- **R3.2 y R3.4 no generan tarea de edición de prosa** en `sdd/specs/access-notifications.md`.
  R3.4 sí genera tarea: dejar la decisión **escrita** (miembro de enum ≠ sumidero para este
  guardián) en el design, en la spec nueva y en la aclaración del residual 8.
- **D11 genera tarea propia** y no está en ninguna AC del proposal.
- **La cifra del residual 5 se re-mide** en el momento de implementar (era 36, hoy 49 con el eje
  viejo y 38 con el nuevo), y se recuenta contra la fuente en vez de incrementarse.
- **R1.5 se verifica dos veces**: con el eje viejo (3 = 3, prueba que la mudanza no movió el
  alcance) y con el nuevo (0 = 0).
