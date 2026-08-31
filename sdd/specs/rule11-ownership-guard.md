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
  dentro del workflow. No es comodidad: una puerta de área sería **un segundo sitio donde
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
  el mecanismo, no ninguna columna—, THE SYSTEM SHALL no reportarlo. Medido al decidirlo: dentro
  del alcance no aportaba ni un verdadero positivo, y aportaba los tres falsos que tenían `main` en
  rojo, que eran atribuciones de miembros de `NotificationType` cazadas por accidente a través de
  una palabra que habla del mecanismo. Por eso esos tres bloques **no se reescribieron**: nunca
  fueron infractores.
- THE SYSTEM SHALL declarar por escrito, junto al propio guardián, lo que su verde **no** cubre, y
  SHALL acompañar cada exclusión declarada de su **coste medido** en bloques.

## Verification

- `make check-rule11-ownership` — cero infractores y salida 0, sin Docker y sin stack.
- `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/test_rule11_ownership.py -q`
  — las meta-pruebas del guardián, que incluyen un caso en rojo por cada forma de fallo cerrado y
  el ancla entre la frase de alcance de la regla 11 y `SCOPE`.
- El check `rule11-ownership` se ejecuta sobre un Pull Request cuyo diff sea **sólo prosa** y sobre
  otro cuyo diff sea **sólo `backend/**`**, y reporta en los dos.
