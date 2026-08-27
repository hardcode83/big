# Design: photo-cache-control-assertion-bound

## Context

`backend/app/integrations/api/signed_media.py:182-204` ya la hace bien: `serve_signed_object` lee el reloj **una vez** (`now_utc()`), lo pasa al caso de uso para verificar la firma, y estampa `Cache-Control: private, max-age=<exp - now_server>` acotado por arriba a `SIGNED_URL_TTL_SECONDS` (3600) y por abajo a 0 (`signed_media.py:278`). El reloj único es lo que evita que un desfase entre verificación y estampado entregue un `max-age` que sobreviva a la credencial.

El test `backend/tests/maintenance/test_serve_photo_api.py::test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature` (líneas 203-219) hace una captura de `request_time` conceptual distinta: mide `remaining = int(exp) - int(time.time())` **al asertar**, no al emitir la petición, y compara contra `abs(max_age - remaining) <= 5`. Bajo carga de la máquina ese desfase supera 5 s (observado `abs(3600 - 3594)` el 2026-08-23); aislado, pasa 14/14. La corrección es del **contrato del test** y no de la ruta: ya existe un test hermano (`test_every_refusal_carries_nosniff_and_no_store`, líneas 342-353) que prueba `Cache-Control: no-store` en las negativas, también con tolerancia cero, así que el patrón "capturar al inicio" ya es familiar en el fichero.

La ruta servida no se toca (`R3.1` del proposal). El cambio vive en el fichero de test y solo en él.

## Decisions

### D1 — Capturar el reloj con `time.time()`, no `time.monotonic()`

**Chosen:** `request_time = time.time()` en una sola línea antes del `photo_api.get(...)`.

`now_utc()` del servidor (`backend/app/core/time.py`) devuelve `datetime.now(timezone.utc)`, cuya base es el mismo reloj de pared que `time.time()`. Una diferencia de `BOUND` segundos entre uno y otro es exactamente el coste de procesar la petición. `time.monotonic()` rechaza la comparación directa —tiene una época no especificada y no se puede restar de un `exp` que viene de `time.time()`—. La elección es obligatoria: usar `time.monotonic()` aquí requeriría reescribir la mitad del contrato de la firma, no es scope de este change.

Rejected: `time.monotonic()` — base distinta, no comparable con `int(exp)`.

Rejected: `freezegun` / `pytest.MonkeyPatch` — `R3.2` del proposal prohíbe introducir fixtures nuevos fuera del fichero, y `freezegun` contamina los demás tests de la misma fixture (`photo_api`).

### D2 — `BOUND = 10` segundos, declarado en el módulo

**Chosen:** constante `BOUND_SECONDS = 10` al inicio del fichero de test, con un comentario de tres líneas explicando que **estrictamente mayor** que el peor desfase medido (`abs(3600 - 3594)` → 6 s el 2026-08-23, panel de QA del change `demo-user` archivado el 2026-08-24) y deja 4 s de cabeza para futuros entornos más cargados.

`10` cumple `R2.2` del proposal (≥ 6) sin convertir la cota inferior en un chequeo trivial. La alternativa `5` reproduce el bug original; la alternativa `30` diluye la cota a un punto donde ya no prueba nada sobre la latencia del procesado. El valor exacto es empírico y se documenta con la medición que lo motivó, no como constante «razonable».

Rejected: `BOUND = 5` — el valor que tenía la tolerancia anterior; es exactamente la magnitud del fallo.
Rejected: `BOUND = 30` — relaja la cota a un valor que ya no es sensible a la latencia de la ruta.

### D3 — Captura de `request_time` como línea única antes del `photo_api.get`

**Chosen:**

```python
photo = await _upload(photo_api, world, db_session)
_, exp, _ = _parts(photo["url"])

request_time = time.time()                       # captura al emitir, no al asertar
response = await photo_api.get(photo["url"])

cache_control = response.headers["cache-control"]
assert cache_control.startswith("private, max-age=")
max_age = int(cache_control.rsplit("=", 1)[1])

# El servidor usa el mismo reloj de pared; el desfase es el tiempo de procesado.
assert 0 < max_age <= SIGNED_URL_TTL_SECONDS, (
    f"max-age={max_age} fuera de la cota del TTL: "
    f"0 < max-age <= {SIGNED_URL_TTL_SECONDS}"
)
assert max_age <= int(exp) - int(request_time), (
    f"max-age={max_age} promete más de lo que le queda a la firma "
    f"al recibir la petición (exp={exp}, request_time={request_time})"
)
assert max_age >= int(exp) - int(request_time) - BOUND_SECONDS, (
    f"max-age={max_age} recorta demasiado: el servidor devolvió "
    f"al menos {BOUND_SECONDS} s menos de lo que quedaba "
    f"(exp={exp}, request_time={request_time}, BOUND_SECONDS={BOUND_SECONDS})"
)
```

Los tres mensajes incluyen los tres términos de la cota (`max_age`, `exp`, `request_time` y donde aplique `BOUND_SECONDS`) —cumple `R1.4`— para que el siguiente investigador entienda qué se compara sin leer el comentario. La forma del comentario (`exp - request_time - BOUND_SECONDS`) se documenta explícitamente **arriba** del bloque, diciendo que expresa "lo que le quedaba a la firma al recibir la petición, menos un margen de procesamiento" —cumple `R2.1` y prohíbe las palabras «igualdad con tolerancia» o «tiempo restante medido al asertar».

Rejected: `time.monotonic_ns()` para precisión — el desfase se mide en segundos enteros y el ruido de precisión no aporta.

Rejected: Capturar `request_time` con `monkeypatch` sobre `time.time` — añade una fixture y deja al test dependiendo de `pytest.MonkeyPatch`, que `R3.2` prohíbe.

### D4 — Caso parametrizado con TTL corto para probar la cota superior explícitamente

**Chosen:** añadir un segundo test, `test_max_age_does_not_exceed_the_signature_remaining_at_request_time`, parametrizado sobre `expires_in` (30 s y 5 s), que ejercita la **cota superior** de `R1.2` con una firma deliberadamente corta. La razón: en el test principal la firma dura 3600 s, así que `max_age <= SIGNED_URL_TTL_SECONDS` y `max_age <= exp - request_time` son indistinguibles — un servidor que devolviera siempre `3600` pasaría la primera y fallaría la segunda sólo porque la firma es corta. Con `expires_in = 30`, la cota superior es 30 s y un servidor descontrolado se separa de la cota del TTL por un factor de 120×.

```python
@pytest.mark.parametrize("expires_in", [30, 5])
async def test_max_age_does_not_exceed_the_signature_remaining_at_request_time(
    photo_api, world, db_session, expires_in
):
    await _local(db_session, world.tenant.id)
    photo = await _upload_with_expires_in(photo_api, world, db_session, expires_in=expires_in)
    _, exp, _ = _parts(photo["url"])

    request_time = time.time()
    response = await photo_api.get(photo["url"])

    cache_control = response.headers["cache-control"]
    max_age = int(cache_control.rsplit("=", 1)[1])

    assert max_age <= int(exp) - int(request_time), (
        f"max-age={max_age} excede lo que quedaba al recibir la petición "
        f"(exp={exp}, request_time={request_time}, ttl firmado={expires_in})"
    )
```

`_upload_with_expires_in` reutiliza la lógica de `_upload` pero pasa `expires_in` explícito al endpoint. Si `_upload` no admite el parámetro, se le añade — un argumento opcional con default `None` que delegue en el comportamiento actual cuando se omita. Esa firma no cambia nada del contrato publicado.

Rejected: parametrizar el test principal — diluye su lectura y mezcla dos cosas distintas (la cota inferior del original y la cota superior del nuevo).

Rejected: añadir un test aparte no parametrizado con TTL=30 — la cobertura es la misma, pero perdemos el caso TTL=5 que es donde un servidor descontrolado falla más espectacularmente (`3600 vs 5`).

### D5 — `_upload` acepta `expires_in` opcional

**Chosen:** extender la firma de `_upload` con un kwarg `expires_in: int | None = None`. Cuando es `None`, se conserva el comportamiento actual (el endpoint decide su propio TTL). Cuando se da un valor, se envía explícito al endpoint. Esto es **una sola línea** y no afecta a ningún otro call site (todos pasan por nombre o sin pasar nada nuevo).

Rejected: añadir un `_upload_with_expires_in` separado — duplica la lógica del POST y abre la puerta a que se desincronicen del endpoint real.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Tests | `backend/tests/maintenance/test_serve_photo_api.py` | Sustituir la aserción `abs(max_age - remaining) <= 5` por el bloque de tres aserciones de D3 con `request_time` capturado al inicio. Añadir constante `BOUND_SECONDS = 10` con comentario. Extender `_upload` con `expires_in` opcional (D5). Añadir el test parametrizado de D4. Renombrar el docstring del test principal para que diga "lo que le quedaba a la firma al recibir la petición" y no "igualdad con tolerancia". |
| Backend | ninguno | `R3.1` del proposal prohíbe tocar `app/maintenance/api/photos_router.py`, `app/integrations/api/signed_media.py`, `app/integrations/domain/storage.py` y `app/integrations/infrastructure/storage.py`. |

## Data & interfaces

Ninguno. No hay migración, no hay cambio de contrato de API, no hay nuevo evento, no hay nueva variable de entorno. La firma del endpoint no cambia (`POST /api/v1/incidents/{id}/photos` ya acepta `expires_in` por su schema actual; verificar en el design de `incident-photos` antes de implementar).

## Risks & mitigations

- **Riesgo 1 — `BOUND_SECONDS = 10` se queda corto en una máquina futura más lenta**. Mitigación: el valor es editable y deja un comentario que apunta a la medición que lo motivó. Si el panel de QA observa un nuevo `abs(...)` por encima de 10 s, basta subir la constante; ningún contrato del lenguaje ni del runtime la acota.
- **Riesgo 2 — el reloj del servidor y el del test difieren en más de `BOUND_SECONDS` por un salto de zona horaria o un desajuste de NTP**. Mitigación: ambos usan `time.time()` / `datetime.now(timezone.utc)`, que son POSIX-time UTC en máquinas razonables. Si un entorno tiene drift documentado, lo correcto es arreglar NTP, no inflar `BOUND_SECONDS`. El comentario en la constante dice esto explícitamente.
- **Riesgo 3 — el cambio del test se confunde con un cambio de comportamiento en review**. Mitigación: `git diff` afecta a un único fichero (`test_serve_photo_api.py`), `R3.1` del proposal lo prohíbe fuera de ahí, y la sección Verification de `tasks.md` publica la salida cruda de `pytest -v` para ese test antes y después.
- **Riesgo 4 — el gemelo de limpieza tiene el mismo defecto y este change no lo arregla**. Mitigación: `R3.3` y el `Out of scope` lo nombran. Si la revisión detecta un defecto análogo en `backend/tests/cleaning/test_serve_photo_api.py`, abre su propia entrada en el roadmap y se mide contra el mismo `BOUND_SECONDS` propuesto aquí.

## Open questions

Ninguna que requiera decisión del usuario antes de implementar. La elección de `BOUND_SECONDS = 10` es empírica y documentada; si la revisión prefiere `15` o `20`, se cambia en `tasks.md` sin afectar al diseño.