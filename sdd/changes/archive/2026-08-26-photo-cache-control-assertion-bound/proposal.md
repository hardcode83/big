# Proposal: photo-cache-control-assertion-bound

## Why

`backend/tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature` afirma que el `max-age` del `Cache-Control` que sirve `GET /api/v1/incident-photos/{photo_id}` es **igual** a lo que le queda a la firma HMAC, con un margen de tolerancia de cinco segundos (`assert abs(max_age - remaining) <= 5`). Bajo carga de la máquina esa diferencia se pasa de cinco segundos y el test falla en rojo aunque la ruta haga exactamente lo que R4.5 de `sdd/specs/incident-photos.md:216-220` declara (`Cache-Control: private, max-age=<lo que le queda a la firma>`, acotado por arriba al TTL de la firma y por abajo a cero). Reproducido el 2026-08-23 con cuatro agentes de revisión corriendo en el mismo stack (`abs(3600 - 3594)`); aislado, pasa 14/14. Es un defecto del contrato del test, no del comportamiento bajo prueba, y se arrastró sin arreglar desde `demo-user` (archivado 2026-08-24, §Roadmap candidates) porque aquel change no tocaba `maintenance/`.

**Fuente**: entrada del roadmap `photo-cache-control-assertion-bound` (size: S · kind: tech, `sdd/roadmap.md:197`).

## What changes

El test `test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature` sustituye la comparación `assert abs(max_age - remaining) <= 5` —donde `remaining` se mide al asertar— por una cota calculada al **momento de emitir la petición**: el `max-age` que sirve la ruta debe estar comprendido entre `int(exp) - request_time - BOUND` y `int(exp) - request_time`, donde `request_time` se captura una sola vez antes del `photo_api.get(...)`. Las cotas independientes `0 < max_age` y `max_age <= SIGNED_URL_TTL_SECONDS` se conservan. No se toca la ruta servida, no se toca `SIGNED_URL_TTL_SECONDS`, y no se toca ningún otro test del fichero ni de su gemelo de limpieza.

## Requirements

### R1 — La aserción deja de depender del reloj del aserto

**As a** mantenedor de la suite del backend, **I want** que la sensibilidad al reloj de `test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature` desaparezca, **so that** la suite no se ponga roja por segundos cuando varios agentes de revisión conduzcan el mismo stack o cuando CI cargue la máquina.

Acceptance criteria:

1. WHEN el test ejecuta el GET anónimo sobre la URL firmada, THE SYSTEM SHALL comparar el `max-age` de la respuesta contra una **cota calculada al emitir la petición** —`request_time = time.monotonic()` o `time.time()` capturado en una sola línea antes del `photo_api.get(...)`— y NEVER SHALL contra `time.time()` evaluado al asertar.
2. THE SYSTEM SHALL sustituir `assert abs(max_age - remaining) <= 5` por un par de cotas equivalentes en semántica R4.5: `max_age <= int(exp) - int(request_time)` (la respuesta no puede prometer más tiempo del que le quedaba a la firma al recibirla) y `max_age >= int(exp) - int(request_time) - BOUND` (la ruta devuelve la mayor parte de lo que quedaba, salvo el tiempo de procesamiento absorbido por `BOUND`).
3. THE SYSTEM SHALL mantener las cotas independientes `0 < max_age` y `max_age <= SIGNED_URL_TTL_SECONDS`, porque R4.5 declara ambas y la sustitución de R1.2 no las relaja.
4. WHEN el `max-age` declarado por la ruta cae fuera de la cota superior de R1.2, THE SYSTEM SHALL hacer fallar el test con un mensaje que incluya el valor observado y los tres términos de la cota (`exp`, `request_time`, `BOUND`), de modo que el siguiente investigador no necesite el comentario para entender qué se compara.

### R2 — La semántica de R4.5 sigue probada, no relajada

**As a** revisor de seguridad, **I want** que la aserción reformulada siga probando que `max-age` está **acotado por lo que le queda a la firma al recibir la petición**, **so that** la cobertura de R4.5 en `sdd/specs/incident-photos.md` no se pierda por arreglar el test.

Acceptance criteria:

1. THE SYSTEM SHALL documentar en un comentario del test que la nueva cota expresa "lo que le quedaba a la firma al recibir la petición, menos un margen de procesamiento", y NEVER SHALL el comentario hablar de "igualdad con tolerancia" ni de "tiempo restante medido al asertar".
2. THE SYSTEM SHALL elegir `BOUND` con un valor **estrictamente mayor** que el peor desfase observado (≥ 6 segundos, el `abs(3600 - 3594)` del 2026-08-23) sin relajar la cota superior: la ruta no debe poder prometer **más** tiempo del que tiene la firma, solo **menos** dentro del margen.
3. WHEN un test ejercita `max-age` justo en el límite de R1.2, THE SYSTEM SHALL demostrar con un caso añadido (parametrizado o como segundo `assert` con un valor exacto) que la cota superior **sí** se aplica — no basta con que la cota inferior cubra el peor caso.

### R3 — El comportamiento bajo prueba no cambia

**As a** revisor del panel, **I want** que la ruta `GET /api/v1/incident-photos/{photo_id}` quede intacta, **so that** la corrección del test no se confunda con un cambio de comportamiento.

Acceptance criteria:

1. THE SYSTEM SHALL no modificar `app/maintenance/api/photos_router.py`, `app/integrations/api/dependencies.py`, `app/integrations/infrastructure/storage.py` ni `app/integrations/domain/storage.py`, salvo si el cambio fuera estrictamente necesario para que la nueva aserción compile, lo cual se documenta en el design.
2. THE SYSTEM SHALL no introducir fixtures, helpers ni imports nuevos fuera del fichero de test `tests/maintenance/test_serve_photo_api.py`.
3. THE SYSTEM SHALL no tocar `backend/tests/cleaning/test_serve_photo_api.py`; si tiene un defecto análogo, va a su propia entrada del roadmap.

### R4 — Verificación

**As a** quien ejecuta el panel de QA, **I want** que la corrección sea demostrable **en rojo antes de verde** y estable bajo carga sintética, **so that** la entrada del roadmap quede cerrada sin reabrir el patrón `rtk-collapses-test-output-to-false-green` y sin que la cobertura dependa del reloj de la máquina.

Acceptance criteria:

1. WHEN el panel de QA reproduce el defecto original, THE SYSTEM SHALL demostrar el test **fallando en rojo** con la aserción `assert abs(max_age - remaining) <= 5` bajo carga sintética —`taskset -c 0-3` envolviendo el `pytest` de la fixture, o `stress -c N` durante la ejecución del test—, midiendo el desfase `abs(max_age - remaining)` y verificando que supera los 5 segundos.
2. WHEN el panel de QA verifica la corrección, THE SYSTEM SHALL pasar el test en verde tras la sustitución de R1.2 en las mismas condiciones (mismo `taskset` / `stress`) y en serie (`pytest` sin paralelizar).
3. THE SYSTEM SHALL pasar la suite completa del backend (`docker compose exec backend uv run pytest`) sin regresiones, medida en este worktree contra `origin/main`, y la cifra se compara contra el `npm test`/`pytest` **de partida** del propio worktree, no contra un número escrito en `sdd/project.md`.
4. THE SYSTEM SHALL documentar el resultado de R4.1–R4.3 en la sección Verification de `tasks.md` con la salida cruda de `pytest -v` para el test afectado, sin filtrar por `rtk` (la lección de `rtk-collapses-test-output-to-false-green`).

## Out of scope

- Cambiar la implementación que estampa `Cache-Control` en `app/integrations/infrastructure/storage.py` o en `ConfiguredFileStorageFactory`: la ruta ya cumple R4.5, el contrato del test es el que está mal.
- Cambiar `SIGNED_URL_TTL_SECONDS` ni los clamps de headers en `app/integrations/domain/storage.py`.
- Tocar `backend/tests/cleaning/test_serve_photo_api.py`: el test de limpieza valida los `directives` del `Cache-Control` con `set(...)` y `== "no-store"`, no usa la igualdad con tolerancia, y su patrón queda fuera. Si tuviera un defecto análogo, abriría su propia entrada en el roadmap.
- Tocar el resto de tests de `test_serve_photo_api.py` aunque compartan fixture.
- Migrar la fixture `photo_api` a otro patrón de medición (`freezegun`, `pytest.MonkeyPatch`, etc.). Se prefiere captura explícita de `request_time` por ser legible y no contaminar otros tests de la fixture.
- Ampliar la cobertura del cache-control con `BoundedTimer` u otros puertos de tiempo; pertenece a su propia entrada si alguien lo pide.

## Affected specs

- `sdd/specs/incident-photos.md` — no se modifica (R4.5 ya declara el comportamiento correcto). El cambio del test alinea la verificación con R4.5; el archivo del cambio es lo que se archiva.
- `sdd/specs/file-storage.md` — no se modifica (la regla del `Cache-Control` derivado de la firma ya vive aquí).
- `sdd/specs/testing.md` — no se modifica (steering de fase `tasks, run`, no `new`; el cambio se atiene a sus tipos y a la convención "tests junto al dominio que cubren").
