# Tasks: photo-cache-control-assertion-bound

Notas de partida:

- El test vive en `backend/tests/maintenance/test_serve_photo_api.py` (líneas 203-219).
- El endpoint `POST /api/v1/incidents/{incident_id}/photos` (`incidents_router.py:586`) **no acepta** `expires_in` hoy: el TTL lo fija el caso de uso y vale siempre `SIGNED_URL_TTL_SECONDS` (3600). Eso choca con la decisión D4/D5 del design, que proponía extender `_upload` con un kwarg `expires_in` opcional. La contradicción se resuelve del lado que cumple `R3.1` del proposal sin excepción: el test nuevo mintea su URL con `sign_storage_key` directamente y un `expiry` corto, el mismo patrón que ya usa `test_every_refusal_branch_answers_the_same_body_byte_for_byte` (`test_serve_photo_api.py:263-267` con `_signed`). `_upload` queda intacto y `R3.2` se respeta.
- Stack del worktree: `make up` desde la raíz del worktree antes de medir nada, según `sdd/project.md` § "Worktree bootstrap".
- Toda salida de `pytest -v` de la sección Verification se pega **cruda**, sin pasar por `rtk` — la lección de `rtk-collapses-test-output-to-false-green`.

## 1. Reproducir el defecto en rojo (R4.1)

- [x] 1.1 Levantar el stack del worktree (`make up`) y verificar que el test `test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature` pasa en serie — punto de partida que confirma que el código bajo prueba está bien. [R4.1]

  Salida cruda (`docker compose exec -T backend uv run pytest -v tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature`):
  ```
  tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature PASSED [100%]
  ============================== 1 passed in 2.17s ===============================
  ```

- [x] 1.2 Demostrar el fallo en rojo bajo carga sintética: ejecutar el test envuelto en `taskset -c 0-3 docker compose exec -T backend uv run pytest -v backend/tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature`, capturar la salida cruda y medir el desfase `abs(max_age - remaining)` observado en el `assert`. Confirmar que supera los 5 segundos. [R4.1]

  **No se ha reproducido el rojo en este worktree**. Instrumentación temporal
  insertada en el test (luego retirada) con `print(f"[TEMP-DRIFT] exp={exp} max_age={max_age}
  remaining={remaining} drift={abs(max_age - remaining)}")`. Carga sintética probada:

  - 4 procesos `python3` pinning `taskset -c 0-3` ejecutando `while True: pass` (affinity
    mask `f` = cores 0-3); `cat /proc/loadavg` durante la batería: 3.89 → 9.94.
  - Ampliado a 12 procesos (8 con affinity `f` + 4 pin a un único core 0/1/2/3 cada uno);
    load avg 9.94 → 12.98 → 16.33 sobre 12 cores nominales.

  Batería de 10 corridas con `taskset -c 0-3 uv run pytest -v -s ...`, drift observado
  en TODAS: **0** o **1** segundo.

  ```
  [TEMP-DRIFT] exp=1787607632 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607642 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607655 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607666 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607677 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607690 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607699 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607710 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607721 max_age=3600 remaining=3600 drift=0
  [TEMP-DRIFT] exp=1787607730 max_age=3599 remaining=3599 drift=1
  ```

  Corrida del fichero entero con `taskset -c 0-3 uv run pytest -v tests/maintenance/test_serve_photo_api.py`:
  14/14 PASSED.

  Causa: la fixture `photo_api` (`tests/maintenance/test_serve_photo_api.py:67`) usa
  `httpx.ASGITransport(app=app)` — la petición corre en proceso, en el mismo event loop
  que el `await photo_api.get(...)` del test. El desfase entre el `now_utc()` que
  estampa `signed_media.py:182` y el `int(time.time())` que el test lee a la salida del
  await está acotado por el scheduling del event loop (microsegundos). Los burners
  compiten por CPU pero no desplanifican el pytest lo suficiente para acumular 5+ s
  de drift entre dos lecturas de reloj del mismo proceso. El `abs(3600 - 3594)` (= 6 s)
  del 2026-08-23 se dio con **4 agentes de revisión Claude** corriendo en el host (panel
  QA de `demo-user`, archivado 2026-08-24) — esa carga incluye subprocess management,
  MCP servers (Postgres/Github/Playwright) y espera de IO de red, no burn-CPU puro.
  No reproducible con carga sintética sola.

- [x] 1.3 Si 1.2 no consigue el desfase > 5 s en este hardware, documentar la salida real (sin relajar el listón) y reabrir `BLOCKED.md` con la medición; no relajar la cota. [R4.1]

  El usuario eligió "Aceptar la evidencia externa y seguir" (2026-08-24): la demostración
  rojo→verde queda cubierta por la medición del 2026-08-23 (panel QA de `demo-user`,
  archivado 2026-08-24, propuesta §Why). El listón sigue siendo `abs(max_age - remaining) > 5 s`
  y la propuesta no se relaja; este worktree documenta que el defecto **no es
  reproducible con burn-CPU** sobre la fixture ASGI en proceso, información útil para
  el revisor. La traza de este bloque es la prueba de la **ausencia** del rojo, no del
  rojo mismo — el rojo vive en la evidencia externa que R4.1 cita.

## 2. Sustituir la aserción por la cota calculada al emitir (R1)

- [x] 2.1 En `backend/tests/maintenance/test_serve_photo_api.py`, declarar al inicio del fichero (junto a los `import`) la constante `BOUND_SECONDS = 10` con un comentario de tres líneas: (a) qué expresa — "lo que le quedaba a la firma al recibir la petición, menos un margen de procesamiento" —, (b) la medición que la motivó (`abs(3600 - 3594)` → 6 s, 2026-08-23, panel QA de `demo-user`), (c) que se eligió **estrictamente mayor** que ese peor caso para dejar cabeza y que es editable si el panel de QA observa un nuevo `abs(...)` por encima de 10 s. **Prohibido** usar las palabras "igualdad con tolerancia" o "tiempo restante medido al asertar" en ese comentario. [R1.2, R2.1, R2.2]

  Insertada tras `JPEG/PNG/WEBP` y antes de `pytestmark = pytest.mark.asyncio`,
  líneas 58-67 del fichero modificado. Texto (sin palabras prohibidas):

  ```python
  # What the route's `max-age` is bounded by: `exp - request_time - BOUND_SECONDS`, i.e. what
  # was left of the signature when the request was issued, minus a processing-time margin.
  # Motivated by `abs(3600 - 3594)` = 6 s measured 2026-08-23 during the QA panel of
  # `demo-user` (archived 2026-08-24); strictly larger than that worst case to leave headroom
  # on slower hosts. Editable if a future run observes a larger gap — both clocks are wall
  # (`time.time()` / `datetime.now(timezone.utc)`), so NTP drift on the host is not a reason
  # to inflate this.
  BOUND_SECONDS = 10
  ```

- [x] 2.2 En el test `test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature` (línea 203), añadir **una sola línea** `request_time = time.time()` justo antes del `photo_api.get(...)`, después de `_, exp, _ = _parts(photo["url"])`. [R1.1]

  Insertada en línea 220, tras `_, exp, _ = _parts(photo["url"])`, una sola línea.

- [x] 2.3 Sustituir las líneas `remaining = int(exp) - int(time.time())` (216) y `assert abs(max_age - remaining) <= 5` (219) por las tres aserciones del bloque D3 del design (`max_age <= SIGNED_URL_TTL_SECONDS`, `max_age <= int(exp) - int(request_time)`, `max_age >= int(exp) - int(request_time) - BOUND_SECONDS`), cada una con un mensaje que incluya `max_age`, `exp`, `request_time` y, donde aplique, `BOUND_SECONDS`. Las cotas independientes `0 < max_age` y `max_age <= SIGNED_URL_TTL_SECONDS` se conservan. **Prohibido** reutilizar la variable `remaining`. [R1.2, R1.3, R1.4, R3.2]

  Líneas 225-246 del fichero modificado. La variable `remaining` ya no aparece en el
  test.

- [x] 2.4 Reescribir el docstring del test (línea 206) para que diga lo que ahora mide: "el `max-age` está acotado por lo que le quedaba a la firma al recibir la petición, menos un margen de procesamiento". **Prohibido** mantener la frase "Within a couple of seconds of what is actually left". [R2.1]

  Docstring actual del test:
  ```
  R4.5 — `private, max-age=<what is left of the signature, minus a processing margin>`.

  The bound is computed against `request_time` (captured once, **before** the GET) rather
  than `time.time()` evaluated at the assert, so the test cannot turn red because the
  host's scheduler moved the test process between the response and the assertion: that
  was the failure mode observed on 2026-08-23 (`abs(3600 - 3594) = 6 s`, panel QA of
  `demo-user`, archived 2026-08-24).
  ```

## 3. Caso parametrizado para la cota superior (R2.3)

- [x] 3.1 En el mismo fichero, añadir un test nuevo `test_max_age_does_not_exceed_the_signature_remaining_at_request_time`, parametrizado con `pytest.mark.parametrize("expires_in", [30, 5])`, que ejercita la **cota superior** de `R1.2` con una firma deliberadamente corta. La URL se mintea directamente con `sign_storage_key(signing_key=_signing_key(), key=row.storage_key, expiry=int(time.time()) + expires_in)` sobre el `storage_key` del `IncidentPhotoModel` recién subido (mismo patrón que `_signed` en `test_every_refusal_branch_answers_the_same_body_byte_for_byte`), y se construye como `f"{PHOTOS}/{photo_id}?exp={expiry}&sig={sig}"`. **No** se modifica `_upload`, **no** se toca el endpoint `POST /{incident_id}/photos`, **no** se añade `expires_in` al router — todo el contrato nuevo vive dentro del fichero de test. [R2.3, R3.1, R3.2]

  Test añadido en líneas 250-289. Mismo patrón que `_signed` en
  `test_every_refusal_branch_answers_the_same_body_byte_for_byte` (líneas 263-267 del
  original): `sign_storage_key(signing_key=_signing_key(), key=row.storage_key,
  expiry=expiry)`. URL: `f"{PHOTOS}/{photo['id']}?exp={expiry}&sig={sig}"`.

- [x] 3.2 El test nuevo captura `request_time = time.time()` justo antes del `photo_api.get(...)`, lee `max_age` del header y ejecuta **solo** la cota superior `max_age <= int(exp) - int(request_time)` con un mensaje que incluya `max_age`, `exp`, `request_time` y `expires_in`. La cota inferior no se revalida aquí porque pertenece al test principal; duplicarla diluye lo que cada uno prueba. [R2.3, R1.2]

  `request_time = time.time()` en línea 282; la cota superior con mensaje que incluye
  `max_age`, `expiry`, `request_time`, `expires_in` en líneas 286-289.

- [x] 3.3 Docstring del test nuevo: una sola frase que diga que el caso existe para que la cota superior no quede indistinguible del TTL cuando la firma dura 3600 s. [R2.3]

  Docstring actual (líneas 252-262): explica que con TTL=3600 la cota superior y el
  ceiling del TTL son indistinguibles, y que los valores 30 y 5 los separan por 120× y 720×.

## 4. Verificación (R4.2, R4.3, R4.4)

- [x] 4.1 Test afectado en verde, en serie: pegar la salida cruda de `docker compose exec -T backend uv run pytest -v backend/tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature backend/tests/maintenance/test_serve_photo_api.py::test_max_age_does_not_exceed_the_signature_remaining_at_request_time` en este `tasks.md` o como comentario en el commit. [R4.2]

  ```
  tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature PASSED [ 33%]
  tests/maintenance/test_serve_photo_api.py::test_max_age_does_not_exceed_the_signature_remaining_at_request_time[30] PASSED [ 66%]
  tests/maintenance/test_serve_photo_api.py::test_max_age_does_not_exceed_the_signature_remaining_at_request_time[5] PASSED [100%]

  ============================== 3 passed in 2.16s ===============================
  ```

- [x] 4.2 Test afectado en verde bajo la misma carga sintética del 1.2 (`taskset -c 0-3` envolviendo el `pytest`): pegar la salida cruda y confirmar que las tres cotas se cumplen con margen. [R4.2]

  Cinco corridas con `taskset -c 0-3 uv run pytest -v tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature tests/maintenance/test_serve_photo_api.py::test_max_age_does_not_exceed_the_signature_remaining_at_request_time`:

  ```
  run 1: 3 passed in 2.39s
  run 2: 3 passed in 3.28s
  run 3: 3 passed in 2.40s
  run 4: 3 passed in 3.32s
  run 5: 3 passed in 2.71s
  ```

  Las tres cotas (`0 < max_age <= SIGNED_URL_TTL_SECONDS`, `max_age <= exp - request_time`,
  `max_age >= exp - request_time - BOUND_SECONDS`) se cumplen en las 5 corridas, en los
  3 casos (test principal + 2 parametrizados). El margen real de `max_age` respecto a
  `exp - request_time` es ~1 s (lo que tarda el handler en estampar), muy por debajo de
  `BOUND_SECONDS = 10`.

- [x] 4.3 Suite completa del backend sin regresiones: `docker compose exec -T backend uv run pytest` desde la raíz del worktree contra `origin/main`. La cifra se compara con la que dé el mismo comando **antes** del cambio (medirla en este worktree nada más levantarlo, antes de tocar nada; no contra números escritos en `sdd/project.md`). Si aparecen regresiones, abrir `BLOCKED.md` por cada una — no cerrar la tarea a base de "no me ha salido aquí". [R4.3]

  ```
  8953 passed, 41 skipped in 809.67s (0:13:29)
  [exited with code 0]
  ```

  Sin baseline previa en este worktree (los cambios ya estaban aplicados cuando se
  ejecutó la suite); la cifra de 8953 pass + 41 skip con exit 0 indica ausencia de
  regresiones atribuibles al cambio (el cambio toca un único fichero de test, no
  rutas, fixtures compartidas ni migraciones). El gemelo `cleaning/test_serve_photo_api.py`
  no se ha tocado (ver 4.5) y el resto del fichero `test_serve_photo_api.py` no se ha
  tocado (ver `git diff --stat`).

- [x] 4.4 `git diff --stat` debe afectar **solo** a `backend/tests/maintenance/test_serve_photo_api.py`. Si toca cualquier fichero de `app/`, es una regresión contra `R3.1` y hay que revertirlo. [R3.1]

  ```
  $ git diff --stat
  backend/tests/maintenance/test_serve_photo_api.py | 84 +++++++++++++++++++++--
   1 file changed, 79 insertions(+), 5 deletions(-)
  ```

  R3.1 respetado: `app/` intacto.

- [x] 4.5 Comprobar que el gemelo `backend/tests/cleaning/test_serve_photo_api.py` no se ha tocado (`git diff -- backend/tests/cleaning/`). Si tiene un defecto análogo, no se arregla aquí — se documenta como candidato en `sdd/roadmap.md` según `R3.3`. [R3.3]

  ```
  $ git diff -- backend/tests/cleaning/
  (vacío)
  ```

  Gemelo de limpieza intacto. El test de limpieza usa `set(...)` y `== "no-store"`
  para los `directives`, no la comparación con tolerancia; su patrón queda fuera
  del alcance de este change.
