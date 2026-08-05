# Tasks: local-dev-network-hardening

La sección 1 aplica la postura de red, y la 3 y la 4 alinean la documentación con ella. La
sección 2 **contenía la guardia que la protegía y se retiró del change** el 2026-08-05: su
número se conserva con una nota, y lo que protege la postura hoy es la revisión del diff.

## 1. Postura de red en `docker-compose.yml`

- [x] 1.1 Acotar Postgres a loopback — `docker-compose.yml` línea 12: `"5432:5432"` →
  `"127.0.0.1:5432:5432"`. Añadir comentario sobre el mapeo con el motivo (D6): el puerto
  queda alcanzable desde la máquina y no desde la red. **Sin tocar** `DATABASE_URL`, que va
  por nombre de servicio (`postgres:5432`) y es un camino distinto. [R1]
- [x] 1.2 Acotar Redis a loopback — `docker-compose.yml` línea 23: `"6379:6379"` →
  `"127.0.0.1:6379:6379"`. El comentario aquí dice tres cosas (D6, R2.2, R2.3): que ahí
  viven los contadores del throttle de `backend/app/auth/infrastructure/throttle.py`
  (`login:ip:*`, `login:fail:*`, `login:lock:*`), que **la defensa es este bind y no la
  autenticación de Redis, que no existe** (no hay `requirepass`), y que exponerlo fuera de
  loopback exige resolver la autenticación antes. [R1, R2]
- [x] 1.3 Dejar escrita la asimetría de `backend` y `frontend` — `docker-compose.yml`
  líneas 63-64 y 127-128: los mapeos `8000:8000` y `3000:3000` **no cambian**, y ganan un
  comentario que dice que su `0.0.0.0` es deliberado (prueba en dispositivo real de la LAN,
  proyecto mobile-first) y qué queda expuesto con ello: la UI y la API de un stack de
  desarrollo con datos de prueba, **sin** acceso directo al datastore. Redactado sin afirmar
  que el stack local sea inalcanzable desde la red, porque con estos dos no lo es. [R3]
- [x] 1.4 Verificar el bind efectivo, no suponerlo — **hecho el 2026-08-05** sobre el stack
  levantado desde este worktree, con los puertos liberados tras cerrarse `celery-jobs`.
  Resultados:
  - `docker compose port postgres 5432` → `127.0.0.1:5432`; `redis 6379` → `127.0.0.1:6379`.
  - `docker inspect` sobre los cuatro servicios: `HostIp` es `127.0.0.1` en `postgres` y
    `redis`, y `0.0.0.0` **más `::`** en `backend` y `frontend`. Hallazgo colateral que no
    estaba previsto y conviene registrar: acotar a loopback **también elimina el binding
    IPv6**, mientras los servicios en todas las interfaces sí lo tienen.
  - Alcanzabilidad TCP real desde la IP de LAN de la máquina (`192.168.100.67`), seis casos y
    los seis como se esperaba: `5432` **rechaza**, `6379` **rechaza**, `3000` conecta, `8000`
    conecta, y por loopback `127.0.0.1:5432` y `:6379` **sí** conectan. Eso demuestra a la vez
    R1.3 y la asimetría deliberada de R3.1, y descarta que el rechazo sea un artefacto de red:
    la misma interfaz acepta los otros dos puertos. [R1, R2, R3]
- [x] 1.5 Verificar que no hay regresión en los consumidores legítimos — **hecho el 2026-08-05**
  con el mismo stack de 1.4:
  - **(a) por nombre de servicio**: `backend` y `worker` conectan a `postgres:5432` y
    `redis:6379`; `migrate` terminó en `Exited (0)` sin errores, que es la prueba de que llegó a
    Postgres y aplicó las migraciones. **Corrección al enunciado de esta tarea**: `frontend` no
    habla con los datastores —no tiene `env_file` ni `DATABASE_URL` a propósito— así que pedirle
    que los alcance era un error de la tarea; lo que sí se verificó es su dependencia real,
    `frontend → backend:8000/health` → `200 {"status":"ok"}`.
  - **(b) suite desde el host**: ejecutada de verdad, no razonada.
    `uv run --directory backend pytest tests/test_db_session.py` → **3 passed**, conectando por
    el valor por defecto contra `localhost:5432` de `specs/domain-foundation-core.md:39`.
    Acotada a los tests que tocan la base de datos, que es donde estaba el riesgo; la suite
    completa no aporta nada sobre el bind. **Deriva encontrada de paso**: `sdd/project.md:21`
    afirma que «`uv` no está instalado en el host», y sí lo está
    (`/Users/hardcode/.local/bin/uv`) — anotado abajo como candidato, fuera del alcance de este
    change.
  - **(c) `README.md:19-20`** (`localhost:5432`, `localhost:6379`): cierto, y ahora comprobado
    empíricamente por las sondas de 1.4 y por (b), no por lectura. [R1]

## 2. Guardia de regresión — **RETIRADA de este change** (2026-08-05)

> Esta sección tenía cinco tareas y produjo, ella sola, los ~19 hallazgos del panel a lo largo de
> cinco rondas —cuatro de ellos regresiones del arreglo anterior—, mientras las secciones 1, 3 y 4
> no recibieron ninguno. Por decisión del usuario, la guardia se saca a la entrada
> **`compose-ports-guard`** del roadmap, que hereda íntegro su análisis: los seis criterios que R5
> llegó a tener, el censo de vías de elusión demostradas (dos de ellas todavía abiertas), las ocho
> decisiones de diseño que eran suyas, y el diagnóstico estructural de por qué cada arreglo abría
> la siguiente vía. El `Makefile` y `.github/workflows/compose-ports.yml` se han **retirado** del
> diff. La numeración de las secciones no se reajusta, por el mismo motivo que la de las
> decisiones: cinco rondas de revisión las citan por su número.

## 3. Corregir la redacción que describe una postura inexistente <!-- panel: FAIL 2026-08-04 (D7 incoherente), arreglado en 3.4 -->

- [x] 3.1 Reescribir la exención de la regla 8 en `sdd/steering/security.md:22` — hoy se
  justifica con *«inalcanzable desde fuera de `localhost`»* sobre un mapeo que publicaba en
  todas las interfaces. La nueva redacción se apoya en la postura real (Postgres publicado
  solo en loopback, sin datos reales) y queda **condicionada a ella**, de forma que si el
  mapeo vuelve a `0.0.0.0` el texto quede visiblemente sin fundamento. **Conservar el efecto
  de la exención**: la contraseña del Postgres de desarrollo sigue pudiendo llevar valor por
  defecto funcional en `.env.example` para que `make up` arranque sin pasos manuales. [R4]
- [x] 3.2 Dejar registradas para el archivado las dos correcciones de `sdd/specs/` que este
  change no ejecuta (el flujo SDD actualiza las specs al archivar): la línea 44 de
  `specs/local-environment.md` repite la misma afirmación falsa (*«es un Postgres solo
  alcanzable dentro de la red de compose»*) y necesita la misma corrección que 3.1 (D7), y
  `specs/auth-tenancy.md` debe anotar de qué depende en dev local la garantía del throttle
  de `:207`/`:215`. Verificar que ambas están en la sección **Affected specs** del
  `proposal.md` con esa precisión, para que `/sdd:archive` no dependa de la memoria de nadie.
  [R2, R4]
- [x] 3.3 Barrido de la afirmación falsa por el resto del repositorio — `grep` de las
  formulaciones equivalentes (*«solo alcanzable dentro de la red de compose»*,
  *«inalcanzable desde fuera de localhost»*, *«no publicado»* aplicado a los datastores
  locales) sobre `README.md`, `docs/`, `sdd/steering/` y `infra/environments/dev/RUNBOOK.md`,
  para confirmar que las dos copias conocidas son las únicas. Si aparece una tercera, se
  corrige aquí. **Resultado: apareció una tercera**, `README.md:108`, y se corrigió en este
  change; documentación hizo después su propio barrido independiente y confirmó que no hay una
  cuarta. [R3, R4]

- [x] 3.4 **Arreglar la incoherencia interna de D7** que el panel encontró (hallazgo B) — al
  corregir D7 a «tres ficheros» dejé el marco viejo de «dos copias» en tres sitios de
  `design.md`: el párrafo *Chosen*, la *Nota de proceso* y la fila `README.md` de *Changes by
  area*, que además seguía prediciendo que el README no se tocaba cuando sí se tocó. Los tres
  reescritos, enumerando las tres copias y diciendo cuál se corrige aquí y cuál al archivar.
  Es el modo de fallo que `/sdd:review` advierte: la frase corregida aterriza en el texto
  explicativo y la vieja sobrevive en el artefacto que lee el siguiente implementador. [R4]
- [x] 3.5 **Dejar de sobrevender el cierre del vector** (hallazgo C) — `proposal.md`, sección
  *Out of scope*: la justificación de no añadir `requirepass` afirmaba que R1 quitaba lo que
  hacía explotable la ausencia de contraseña, y eso solo vale para atacantes **remotos**. Se
  acota la afirmación a la explotación desde la red y se declara el residual «mismo host, otro
  proceso local» como aceptado y no como cerrado. Mismo aviso añadido al README, donde lo lee
  quien clona el repo. [R2]

## 4. Documentación <!-- panel: FAIL 2026-08-04 (bloque en sección equivocada), arreglado en 4.3; documentation PASS en re-review -->

- [x] 4.1 `README.md` — subsección nueva `### Postura de red del stack local` dentro de
  `## Arrancar en local`: qué está acotado a loopback y por qué, qué publican `backend`/`frontend`
  y por qué es deliberado, y **que esta postura no tiene comprobación automática todavía**,
  remitiendo a la entrada `compose-ports-guard`. Al retirarse la guardia (2026-08-05) desapareció
  de aquí el comando de `make` y la mención del workflow que esta tarea había añadido; lo que
  `steering/documentation.md` exige del README se cumple igual, porque el change ya no añade
  ningún comando.
- [x] 4.2 Confirmar que el resto del README sigue exacto tras el cambio y no necesita
  edición: las URLs locales de :17-18 (backend `8000`, frontend `3000`) y las de :19-20
  (`localhost:5432`, `localhost:6379`) son todas ciertas con la postura nueva. Dejar
  constancia de la comprobación en vez de asumirla. [R1, R3]

- [x] 4.3 **Mover el bloque de postura de red a la sección correcta** (hallazgo D) — estaba
  anidado bajo `## Tests`, cuando el comando que explica y las URLs que cita viven en
  `## Arrancar en local`. Movido allí, justo tras la lista de comandos. Referente:
  `steering/documentation.md:17`. La mención de una línea que se dejó en `## Tests` apuntando al
  workflow **se retiró** al sacar la guardia del change, junto con el enlace interno. [R3]

## 5. Verification

- [x] 5.1 El stack arranca limpio de cero — **hecho el 2026-08-05**: `make down` seguido de
  `make up` sobre el proyecto de este worktree. `postgres` y `redis` alcanzaron `Healthy`,
  `migrate` corrió y terminó en `Exited (0)` **antes** de que arrancaran `backend`/`worker`, y
  los cinco servicios quedaron arriba con `backend` en `(healthy)`. Coincide con
  `specs/local-environment.md:17-18,25`. Nota de camino: el primer intento falló con
  `socket.gaierror` en `migrate` porque quedaban contenedores en estado `Created` de un intento
  anterior colgados de una red ya eliminada; se resolvió con `make down` y volver a levantar, sin
  tocar volúmenes. [R1]
- [x] 5.2 Suite del backend en verde dentro del contenedor — **hecho el 2026-08-05**:
  `docker compose exec backend uv run pytest` → **2540 passed, 35 skipped en 3m26s**, con los
  datastores acotados a loopback. Es el comando que manda `sdd/project.md:21`. [R1]
- [x] 5.3 Frontend no afectado — **la comprobación que aplica de verdad no es ejecutar la
  suite, es que no hay nada que ejecutar**: `git status --short frontend/` sale vacío, el
  change no toca ni un fichero bajo `frontend/`, y el único cambio de raíz que le podría
  afectar (`docker-compose.yml`) no altera el `3000:3000` ni ninguna variable del servicio.
  Levantar `npm ci` en el worktree para volver a verde una suite sin relación con el diff no
  añade evidencia; el workflow `frontend-tests` la ejecutará igualmente en el PR.
> **5.4 no existe**: era la ejecución en verde de `make check-compose-ports`, y desapareció con
> la retirada de la guardia (2026-08-05). El hueco se conserva por el mismo motivo que los de las
> decisiones y el de la sección 2 — cinco rondas de revisión citan estos números.

- [x] 5.5 Repaso de cobertura de requisitos contra el `proposal.md` — ningún criterio quedó
  sin tarea. Esta tarea **llegó a remitir a un «censo canónico» de `design.md`**, que era la lista
  de casos probados contra la guardia; **ese censo se fue con ella** a `compose-ports-guard` el
  2026-08-05, así que la cita se elimina en vez de dejarla colgando. La cobertura por requisito
  vive aquí, y es la de abajo:
  - **R3 y R4 completos y verificados.** R3.1 en la salida de `docker compose config` (mapeos
    de `backend`/`frontend` intactos); R3.2-R3.4 en los comentarios de `docker-compose.yml` y
    la subsección del README; R4.1-R4.3 en la reescritura de la regla 8, con barrido propio y
    otro independiente del revisor de documentación confirmando que no hay una cuarta copia.
  - **R1 y R2 completos y verificados sobre contenedores reales** (tareas 1.4 y 1.5, hechas el
    2026-08-05 cuando se liberó la ventana de puertos): `docker compose port` y `docker inspect`
    dan `127.0.0.1` en los datastores; desde la IP de LAN los puertos 5432 y 6379 **rechazan**
    mientras 3000 y 8000 conectan, y por loopback los datastores **sí** conectan; los
    contenedores siguen llegando por nombre de servicio; la suite del host conecta por
    `localhost:5432` y la del contenedor pasa entera. R2.2 y R2.3 son constancia escrita y no
    comportamiento, y su redacción se corrigió en 3.5 para no dar por cerrado el residual de
    «mismo host, otro proceso local».
  - **El quinto requisito, la guardia de regresión automática, ya no forma parte de este
    change**: se retiró a `compose-ports-guard` el 2026-08-05 con su análisis íntegro, así que no
    hay criterio suyo que acreditar aquí.
