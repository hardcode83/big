# Guardia de la propiedad de la regla 11

## Purpose

Esta capacidad ejecuta, en local y en cada Pull Request, el guardián que impide que la
**propiedad** de un sumidero de texto en claro se declare fuera de la tabla que la gobierna.
Recorre la prosa y los docstrings del árbol y se pone en rojo nombrando fichero, línea y la frase
exacta cuando un bloque dice **quién escribe** o **quién heredará** una columna del censo en algún
sitio que no sea esa tabla.

**El contrato no vive aquí.** Qué columnas componen el censo, qué forma debe tener cada una, quién
la escribe hoy y qué excepciones están concedidas es materia de
[`steering/security.md` § «Sumideros de texto en claro (regla 11)»](../steering/security.md), que
dice de sí misma que es el único sitio donde vive. Esta spec documenta el **mecanismo**: cuándo se
ejecuta, dónde publica su resultado, cómo falla y dónde está declarado su alcance. Si las dos
discrepan, manda la regla.

Existe como capacidad propia, y no como párrafo de `backend-ci`, porque el guardián dejó de vivir
bajo `backend/` en el change `rule11-guard-trigger-and-scope`: no necesita PostgreSQL, ni Redis, ni
`.env`, ni secret alguno, y da señal en segundos. Es el mismo criterio que separó `api-contract` de
la suite del backend.

**Por qué hizo falta moverlo, que es el defecto que esta capacidad corrige.** El guardián vivía en
`backend/tests/`, y el gate de área de `backend-tests.yml` decide si corre la suite mirando si el
diff toca `backend/**`. Su alcance y su gatillo eran conjuntos **disjuntos**: un commit de sola
prosa —que es exactamente la forma de todo commit de `/sdd:archive`— no ejecutaba la suite que lo
contenía. Medido: en el run 33409418091 de `main`, sobre el commit que introdujo tres bloques
infractores, `backend-tests` salió success y `backend-tests-suite` **skipped**. `main` quedó verde
en CI y rojo en local, y el rojo le habría caído a la siguiente Pull Request que tocara
`backend/**` sin haberlo escrito. Un guardián que reparte el coste al azar no protege.

## Requirements

### Disparador y alcance de ejecución

- WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL ejecutar el
  workflow `rule11-ownership`.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`**, por el motivo que
  [`specs/backend-ci.md`](backend-ci.md) fija para todo el repositorio: un filtro de rutas a nivel
  de disparador no produce check alguno en los PR que no tocan esas rutas.
- THE SYSTEM SHALL ejecutarlo **sin puerta de área de ninguna clase**, ni en el disparador ni
  dentro del workflow. **Y hoy esto no lo impone ninguna prueba**, a diferencia del alcance más
  abajo: es una norma escrita que un revisor humano tiene que sostener. Anclarla
  mecánicamente se intentó y no convergió —el detalle y las tres vías medidas están en el
  candidato de roadmap del change `rule11-guard-trigger-and-scope`—, así que el hueco se
  declara aquí en vez de darse por cerrado. No es comodidad: una puerta de área sería **un segundo sitio donde
  equivocarse sobre el alcance**, que es exactamente el defecto que esta capacidad corrige.
  Ejecutar siempre satisface el requisito por construcción y no por acierto, y el escaneo cuesta
  alrededor de un segundo sobre el árbol entero.
- WHERE el diff de un Pull Request no toque ninguna ruta que el guardián recorra, THE SYSTEM SHALL
  ejecutarlo igualmente y reportar verde. El coste de esa ejecución de más es el precio de no
  tener una segunda declaración de alcance que mantener sincronizada con la primera.

### El check run

- THE SYSTEM SHALL publicar el resultado como un check run **propio**, llamado `rule11-ownership`,
  distinto del de `backend-tests`. El nombre lo toma del **job** y no del workflow, así que el job
  se llama igual que el workflow a propósito.
- **Estado del check.** WHILE el repositorio no disponga de protección de rama compatible, THE
  SYSTEM SHALL ejecutar y reportar `rule11-ownership` **sin** configurarlo como check obligatorio
  para fusionar — igual que `api-contract`, `compose-ports` y `frontend-tests`, y por el mismo
  motivo de plan de GitHub ([`specs/backend-ci.md`](backend-ci.md) §Estado,
  [`docs/adr/0002-github-org-hosting.md`](../../docs/adr/0002-github-org-hosting.md)). Lo que
  sostiene esta guardia mientras tanto es un rojo **visible** en cada Pull Request, no una puerta
  que impida fusionar. El día que haya protección de rama, éste es de los checks que deben pasar a
  obligatorios.

### Independencia del entorno

- WHERE el guardián se ejecute en CI, THE SYSTEM SHALL no requerir PostgreSQL, Redis, `.env` ni
  ningún secret, y SHALL hacerlo **verificable leyendo el workflow**: sin `services:`, sin `env:` y
  sin ninguna referencia a `secrets`.
- THE SYSTEM SHALL implementarlo con biblioteca estándar exclusivamente, de forma que se ejecute
  con el `python3` del runner sin sincronizar el árbol de dependencias del backend.
- WHEN alguien lo ejecute en local, THE SYSTEM SHALL ofrecer `make check-rule11-ownership`, que
  corre con el `python3` del host **sin Docker y sin el stack levantado**, y SHALL dar el mismo
  veredicto que en CI sobre el mismo árbol.
- WHERE se ejecute con el `python3` del host, THE SYSTEM SHALL requerir **Python ≥ 3.11**: el
  guardián usa `enum.StrEnum`, que no existe antes de esa versión, y es el único script de
  `scripts/` que lo hace. El suelo se declara aquí porque abajo de él la vía local no da veredicto
  —muere con un `ImportError` antes de llegar a `main()`—, así que la equivalencia con CI que pide
  el punto anterior sólo se sostiene por encima de él. CI no está afectado: `ubuntu-latest` trae
  3.12.

**El coste declarado de vivir fuera de la suite.** El `pytest` del backend ya **no** ejecuta este
guardián. Quien escriba una atribución en un docstring de `backend/app/**` la ve en CI y en
`make check-rule11-ownership`, no en su suite local. Se acepta a cambio de que el gatillo deje de
estar acoplado al área del diff, que es lo que estaba roto; y la vía local resulta **más barata que
antes**, porque ya no exige contenedor ni stack.

### Alcance recorrido

- THE SYSTEM SHALL derivar qué ficheros recorre de **una sola estructura de datos declarada** en
  `scripts/rule11-ownership.py`, la tupla `SCOPE`, en la que cada entrada lleva su ruta, su tipo y
  **su motivo escrito**, y de la que no queda ninguna ruta literal fuera.
- THE SYSTEM SHALL tratar `SCOPE` como la fuente de esa lista. Esta spec **no la reproduce**: la
  enumeración de qué árboles son censo, cuáles quedan fuera y qué ficheros están exceptuados vive
  en `SCOPE` y, en prosa, en la frase de alcance de la sección de la regla 11 — y una prueba ancla
  las dos en las dos direcciones, de modo que no pueden discrepar en silencio.
- WHEN el guardián reporte un infractor, THE SYSTEM SHALL nombrar **fichero, línea y la frase
  exacta** que disparó el eje.
- WHEN el guardián no encuentre ninguno, THE SYSTEM SHALL **nombrar y contar lo que ha recorrido**,
  para que el verde se lea como «miró esto» y no como «no miró nada».

### Fallo cerrado

- IF cualquier paso de la cadena se rompe, THEN THE SYSTEM SHALL terminar con código distinto de
  cero y **mensaje propio**, nunca en verde y nunca en `skip`. Un `skip` se lee como «no aplica»,
  que es lo peor que puede decir un control de seguridad cuando su entrada ha desaparecido.
- THE SYSTEM SHALL fallar así, como mínimo, en estos casos:
  - el alcance declarado está vacío;
  - un árbol de censo no existe, no contiene ningún fichero de su tipo, o **no aporta ninguno al
    escaneo porque una exclusión se lo está tragando** — tres causas distintas con tres mensajes
    distintos, porque el rojo tiene que decir cuál es;
  - una entrada de exclusión o de excepción ha dejado de corresponder a una ruta que el escaneo
    recorra, en cuyo caso SHALL nombrar la entrada muerta;
  - se recorren menos ficheros de los que el árbol debería tener, en prosa o en código;
  - un fichero del alcance no se puede parsear o no se puede leer, en cuyo caso SHALL nombrarlo.

### Qué es un sumidero para este guardián

- THE SYSTEM SHALL disparar sólo cuando **dos ejes** coincidan en el mismo bloque: nombrar algo que
  la tabla de la regla 11 gobierna, y atribuir su escritor. Un solo eje no se reporta.
- **La atribución de un miembro de un enum no es la de un sumidero, para este guardián.** El eje se
  alimenta de nombres de columna y de tabla, así que un bloque que sólo nombre un tipo de
  notificación no lleva término de sumidero, y eso es deliberado: hay muchos más miembros de enum
  que columnas, se renombran libremente, y perseguirlos sería la lista inmantenible que el change
  fundacional vino a abolir. La regla 11 sigue considerando esa duplicación indeseable; lo que esta
  spec fija es que **este mecanismo no la detecta**, y que su verde no debe leerse como que la
  cubre.
- WHERE un bloque encaje únicamente por el **meta-vocabulario** del censo —las palabras que nombran
  el mecanismo, no ninguna columna—, THE SYSTEM SHALL no reportarlo. Recontado contra el árbol que
  se entrega, ya con `main` fusionado (2026-09-02): dentro del alcance no aporta ni un verdadero
  positivo, y aporta **cuatro** falsos. Tres son los que tenían `main` en rojo
  —`sdd/specs/access-notifications.md:373`, `:526` y `:690`; eran `:372`, `:525` y `:689` antes de
  que la fusión de base insertara una línea encima, y el conjunto exacto lo fija por identidad
  `test_the_declared_cost_of_dropping_the_meta_vocabulary_is_still_what_the_prose_says`—,
  atribuciones de miembros de `NotificationType` cazadas por accidente a través de una
  palabra que habla del mecanismo; por eso esos tres bloques **no se reescribieron**: nunca fueron
  infractores. El cuarto es la línea 11 **de esta misma spec**, el párrafo que declara que el
  contrato no vive aquí: encaja por `censo` y por una de las trece redacciones del eje de propiedad,
  sin atribuir nada. Eran tres
  cuando se decidió D3, antes de que esta spec existiera, y conviene no disimular la mitad
  incómoda: **esta spec da verde gracias al estrechamiento que hace el mismo change**, que es la
  misma autorreferencia que obligó a reescribir la entrada de roadmap de este change y la razón
  concreta de que el meta-vocabulario tuviera que salir.

  > **Este párrafo no cita literalmente ninguna de las trece redacciones del eje de propiedad, y es
  > deliberado — no es estilo.** La primera versión de esta frase sí lo hacía: escribía la redacción
  > entre comillas para explicar por qué encaja la línea 11, y con eso **la propia oración que
  > cuenta pasó a ser el quinto miembro de lo que cuenta**. Lo levantó el panel de review el
  > 2026-09-01, midiendo cinco donde el texto decía cuatro. Subir la cifra a cinco no lo arregla:
  > cualquier frase futura que necesite nombrar la redacción vuelve a moverla, así que la grafía
  > pierde la carrera y el recuento no converge nunca. Lo que sí cierra es que la oración deje de
  > ser miembro del conjunto: se describe el encaje **por referencia** («una de las trece
  > redacciones») en vez de transcribirlo. Si alguien reintroduce la cita literal aquí, el coste
  > declarado deja de ser cuatro y esta sección vuelve a contarse a sí misma.

- THE SYSTEM SHALL declarar por escrito, junto al propio guardián, lo que su verde **no** cubre, y
  SHALL acompañar cada exclusión declarada de su **coste medido** en bloques.

## Verification

- `make check-rule11-ownership` — cero infractores y salida 0, sin Docker y sin stack.
- `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/test_rule11_ownership.py -q`
  — las meta-pruebas del guardián, que incluyen un caso en rojo por cada forma de fallo cerrado y
  el ancla entre la frase de alcance de la regla 11 y `SCOPE`.
- Que el check `rule11-ownership` se ejecuta y reporta por las dos vías de diff —una de sola prosa y
  otra de sólo `backend/**`— no se comprueba en local, porque no hay run sin Pull Request: es la
  primera de las obligaciones de la subsección siguiente, y allí está su forma exacta. No se repite
  aquí para que no haya dos redacciones de la misma exigencia que puedan separarse.

### Obligaciones sobre la Pull Request abierta, antes del merge

Esto vive aquí, y no en el `tasks.md` de un change, por una razón que costó dos gates descubrir: es
verificación que **sólo puede existir cuando hay una Pull Request abierta**, y una lista de tareas
pre-PR no puede contenerla. El workflow dispara en `pull_request` y en `push: branches: [main]`, así
que empujar la rama de una feature no produce ningún run: los ids no existen hasta que hay PR. El
change que creó esta capacidad lo intentó como sección de tareas y chocó dos veces — el gate de ship
rechaza un `BLOCKED.md` no vacío, y el de ciclo de vida rechaza una tarea sin marcar—, que es la
prueba de que el sitio era éste.

**Todas son anteriores al merge**, y el título lo dice porque confundirlo tiene consecuencia: hacer
la comprobación de la base fusionada *después* de fusionar es medirla cuando el rojo ya está en
`main`, que es exactamente lo que esta capacidad existe para evitar.

Quien abra una Pull Request que altere el gatillo, el alcance o el eje de este guardián **debe**
dejar registrada esta evidencia **en el propio change**, en
`sdd/changes/<feature>/tasks.md` § «Registro de evidencia sobre la PR» —un fichero del árbol, que se
puede grepear y que sobrevive al cierre de la PR—, y anclarla con `mark-recertified`. **No vale
dejarla sólo en un comentario de la Pull Request**: no está en el repositorio, no lo lee nadie
después y desaparece con la PR, así que una obligación registrada ahí es una obligación que nadie
podrá comprobar que se cumplió.

- **Las dos vías de diff.** El id de run del check sobre un evento `pull_request` cuyo diff sea sólo
  prosa, y otro cuyo diff sea sólo `backend/**`. En el de sola prosa, `backend-tests-suite` sale
  `skipped` y este check **no** — que es exactamente el defecto que esta capacidad corrige, así que
  conviene anotarlo junto a los ids y no darlo por sabido.

  **Y la PR del propio change no puede dar ninguno de los dos ids, así que la obligación nombra el
  vehículo en vez de dejarlo al lector.** El diff de una PR es `base...head`, que es lo que mide
  `backend-tests.yml` para decidir el área; y una PR que altere el gatillo, el alcance o el eje de
  este guardián toca siempre `scripts/` y casi siempre `sdd/**` y `backend/**` a la vez, así que su
  diff no es «sólo prosa» ni «sólo `backend/**`» por construcción. Los dos ids se toman de **dos
  Pull Requests desechables cuya base es la rama de la PR principal** —no `main`— y **cuyo diff
  completo, `base...head`, no sale de un solo árbol**: una que toque sólo `sdd/**` o `docs/**`, otra
  que toque sólo `backend/**`. Su head arrastra ya el workflow, y `backend-tests-detect` evalúa ese
  mismo diff, que es lo que hace **cierta** la anotación de `backend-tests-suite` `skipped`. Se
  cierran tras registrar los ids. Medir el diff del *push* que provoca un `synchronize` sobre la PR
  principal no vale: el área que `backend-tests` resuelve sigue siendo la del diff completo de la
  PR, así que el contraste que este punto manda anotar no se observaría.

  **La condición es el árbol, no el número de commits, y conviene decirlo porque la primera
  redacción pedía «un solo commit».** Un commit garantizaba la propiedad de forma trivial, pero no
  era la propiedad: lo que `backend-tests-detect` mira es `base...head`, así que una PR sonda con
  varios commits sigue valiendo mientras **todos** toquen el mismo árbol — y eso permite reutilizar
  la misma sonda para los commits en rojo y su revert (el punto siguiente) en vez de abrir una PR
  por evento. Tiene un precio que conviene conocer al leer los ids: los runs del commit anterior
  pueden salir **`cancelled`** por `concurrency` cuando llega el siguiente, así que un
  `backend-tests-suite` en `cancelled` sobre una sonda no es una señal de nada — la fila que importa
  es la del check propio, y el área resuelta se lee en el log de `backend-tests-detect`.
- **El check en rojo por cada forma que dice cazar.** Un commit temporal con un bloque infractor en
  markdown y otro en un docstring o tirada de `#`, el id de run con el check en rojo, y el verde al
  revertirlo. Que la *función* y el *binario* los cazan se prueba en local con las meta-pruebas y con
  `make check-rule11-ownership`; lo que sólo la PR puede probar es que el **check run** se pone rojo.
- **Verde sobre la base fusionada.** El id de run del check `rule11-ownership` reportando **cero
  infractores** sobre la rama con `main` ya fusionado, y no sobre la rama sola: `origin/main` se mueve
  mientras una PR está en vuelo, y fue justamente un commit de archivado aterrizando en `main` lo que
  dejó la base en rojo la primera vez. **Tiene que ser el id de un run del check, no una salida local
  de `make check-rule11-ownership`**: lo que se comprueba aquí es la base fusionada tal como CI la
  ve, y una ejecución local no la ve.

  **Y hay cobertura automática parcial que conviene conocer, porque acota lo que queda a tu cargo.**
  `actions/checkout@v4` sobre un evento `pull_request` no hace checkout de la rama, sino del **merge
  ref** que GitHub calcula (rama ∪ base), así que **cada evento de la PR ya mide la base fusionada**
  sin que nadie lo pida; y `push: branches: [main]` vuelve a medirla después del merge. Lo que **no**
  cubre, y es el motivo de que este punto siga siendo obligación de una persona: GitHub **no**
  re-dispara `pull_request` cuando se mueve la **base**, así que una PR cuyo último evento precede a
  un avance de `main` arrastra un verde caducado. De ahí que el id que se registra deba ser de un run
  **posterior** a la última fusión de `main` en la rama, y sólo hay una forma de conseguirlo: **un
  evento nuevo del head** —el push con el que `/sdd:ship` sincroniza la base, o un commit vacío
  después—, porque es lo único que produce **un run nuevo cuyo `github.sha` es el merge commit
  calculado contra la base de ahora**. (GitHub sí recompone el test-merge cuando la base se mueve;
  lo que no hace es lanzar un run que lo mida, y es el run lo que aquí se registra.)
  **Un re-run no vale**:
  reutiliza el `github.sha` y el payload del evento original, así que `actions/checkout` vuelve al
  merge ref viejo (cuando GitHub no lo ha dejado ya inalcanzable). **Un `workflow_dispatch` tampoco**:
  corre sobre el ref de la rama y no sobre `refs/pull/<n>/merge`, es decir mide la rama sola, que es
  justamente lo que este punto prohíbe.

Y una distinción que no conviene perder, porque confundirla ya descargó un requisito por el camino
equivocado: las vías de **fallo cerrado** del binario (alcance vacío, árbol ausente, fichero
ilegible, entrada muerta…) son evidencia de que el guardián no da falsos verdes, **no** de que
detecte un bloque infractor. Son caminos de código distintos y se demuestran por separado.
