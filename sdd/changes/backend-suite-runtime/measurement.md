# Medición del coste de la suite (R1)

Procedimiento y resultados. Está aquí y no en prosa dentro del design porque R1.1 pide que sea
**repetible por cualquiera**: los dos scripts se pegan tal cual y producen las mismas tablas.

Condiciones de la medición local: **2026-08-10**, worktree `sdd/backend-suite-runtime`, stack propio
de compose (`make up`), contenedor `backend` con **12 núcleos** disponibles. El runner de GitHub
(`ubuntu-latest`, 4 vCPU) es **1,54×** más lento: 15m 34s frente a 10m 06s para la misma suite
(run `31336428305`, 2026-08-09).

## 1. Atribución del tiempo por causa

Plugin de pytest que cronometra cada fixture y cada fase de cada test. Se guarda **fuera del árbol**
para no ensuciar la suite que se está midiendo, y se carga con `-p`:

```bash
mkdir -p /tmp/measure && cat > /tmp/measure/measure_plugin.py <<'PY'
import collections, json, os, time
import pytest

_fixture_time, _fixture_count = collections.Counter(), collections.Counter()
_phase_time, _phase_count = collections.Counter(), collections.Counter()
_session, _with_engine = {}, [0]


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef, request):
    t0 = time.perf_counter()
    try:
        return (yield)
    finally:
        _fixture_time[fixturedef.argname] += time.perf_counter() - t0
        _fixture_count[fixturedef.argname] += 1
        if fixturedef.argname == "test_engine":
            _with_engine[0] += 1


def _phase(name):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        _phase_time[name] += time.perf_counter() - t0
        _phase_count[name] += 1


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    yield from _phase("setup")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    yield from _phase("call")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    yield from _phase("teardown")


@pytest.hookimpl(wrapper=True)
def pytest_collection(session):
    t0 = time.perf_counter()
    try:
        return (yield)
    finally:
        _session["collection_s"] = time.perf_counter() - t0


def pytest_sessionstart(session):
    _session["start"] = time.perf_counter()


def pytest_sessionfinish(session, exitstatus):
    report = {
        "total_s": round(time.perf_counter() - _session["start"], 2),
        "collection_s": round(_session.get("collection_s", 0.0), 2),
        "tests_with_test_engine": _with_engine[0],
        "phases": {k: {"total_s": round(v, 2), "n": _phase_count[k]} for k, v in _phase_time.items()},
        "fixtures_top40": [
            {"name": n, "total_s": round(t, 2), "n": _fixture_count[n]}
            for n, t in _fixture_time.most_common(40)
        ],
    }
    with open(os.environ.get("MEASURE_OUT", "/tmp/measure/report.json"), "w") as fh:
        json.dump(report, fh, indent=2)
PY

docker compose exec -T backend mkdir -p /measure
docker compose cp /tmp/measure/measure_plugin.py backend:/measure/measure_plugin.py
docker compose exec -T \
  -e PYTHONPATH=/measure -e MEASURE_OUT=/measure/baseline.json -e PYTEST_DB_SUFFIX=measure_base \
  backend uv run pytest -q -rs -p measure_plugin
docker compose exec -T backend cat /measure/baseline.json
```

Resultado (**5 329 pasados + 35 omitidos en 618,51s**; la instrumentación cuesta ~2 % sobre los
606,71s sin ella):

| Causa | Tiempo | % |
|---|---|---|
| `create_all` por test (setup de `test_engine`, 1 332 tests) | 343,53s | 55,5 % |
| `drop_all` + `dispose` por test (fase teardown) | 136,67s | 22,1 % |
| Resto de fixtures (`tenant_a` 25,40s/977, `users_by_role_a` 7,11s/512, …) | 39,86s | 6,4 % |
| Cuerpo de los tests (fase `call`) | 92,42s | 14,9 % |
| Recolección y sesión | 2,40s | 0,4 % |
| **Atribuido** | **614,88s** | **99,4 %** |

Fases en crudo: `setup` 383,39s / `call` 92,42s / `teardown` 136,67s sobre 5 364 casos.
La atribución del teardown se cruza con la medición independiente de `drop_all`: 136,67s ÷ 1 332
tests = **103 ms**, y `drop_all` medido aparte da **121 ms**.

## 2. Coste unitario de cada estrategia

```bash
docker compose exec -T -w /app -e PYTHONPATH=/app backend uv run python - <<'PY'
import asyncio, statistics, time, uuid
import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
import app.core.models_registry  # noqa: F401
from app.core.config import settings
from app.core.db import Base

DEV = make_url(settings.database_url)
DB, N = DEV.database + "_cost", 10
URL = DEV.set(database=DB).render_as_string(hide_password=False)
TABLES = list(Base.metadata.sorted_tables)
TRUNCATE = "TRUNCATE TABLE " + ", ".join(f'"{t.name}"' for t in TABLES)
DELETE_ONE = "WITH " + ", ".join(
    f'd{i} AS (DELETE FROM "{t.name}")' for i, t in enumerate(TABLES)
) + " SELECT 1"


async def admin():
    return await asyncpg.connect(user=DEV.username, password=DEV.password,
                                 host=DEV.host, port=DEV.port, database="postgres")


async def main():
    c = await admin()
    await c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
    await c.execute(f'CREATE DATABASE "{DB}"')
    await c.close()
    out = {}
    create, drop = [], []
    for _ in range(N):
        e = create_async_engine(URL, poolclass=NullPool)
        t0 = time.perf_counter()
        async with e.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        create.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        async with e.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        drop.append((time.perf_counter() - t0) * 1000)
        await e.dispose()
    out["create_all"], out["drop_all"] = create, drop

    e = create_async_engine(URL, poolclass=NullPool)
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    for label, sql in (("TRUNCATE", TRUNCATE), ("DELETE 1 stmt", DELETE_ONE)):
        took = []
        for _ in range(N):
            async with e.begin() as conn:
                await conn.execute(
                    text("INSERT INTO tenants (id, name, billing_email, status, created_at,"
                         " updated_at) VALUES (:i, :n, 'ops@example.com', 'ACTIVE', now(), now())"),
                    {"i": uuid.uuid4(), "n": f"t-{uuid.uuid4().hex[:8]}"},
                )
            t0 = time.perf_counter()
            async with e.begin() as conn:
                await conn.execute(text(sql))
            took.append((time.perf_counter() - t0) * 1000)
        out[label] = took
    await e.dispose()
    c = await admin()
    await c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
    await c.close()
    for k, v in out.items():
        print(f"{k:<16} median {statistics.median(v):7.1f} ms  min {min(v):7.1f}  max {max(v):7.1f}")

asyncio.run(main())
PY
```

Medianas de dos ejecuciones del banco, porque el DDL **varía** entre ellas y conviene que se vea:

| Operación | Ejecución 1 | Ejecución 2 |
|---|---|---|
| `Base.metadata.create_all` | 303,6 ms | 195,8 ms |
| `Base.metadata.drop_all` | 120,8 ms | 93,9 ms |
| `TRUNCATE` de las 29 tablas | 112,5 ms | 119,6 ms |
| **Un solo `DELETE` de todas las tablas (CTE)** | **21,1 ms** | **22,9 ms** |
| 29 `DELETE` sueltos | 28,8 ms | — |
| `create_async_engine` + primera conexión | 29,9 ms | — |
| `synchronous_commit = off` sobre `TRUNCATE` / `DELETE` | 119,1 / 20,3 ms (sin efecto) | — |

La variación del DDL (158-337 ms de extremo a extremo en `create_all`) es la razón de que **la cifra
autoritativa por test no sea ésta sino la del §1**, tomada dentro de la suite real: **258 ms** de
setup + **103 ms** de teardown = **361 ms** por test que toca base de datos. El banco sirve para
comparar estrategias entre sí, y para eso su margen sobra: crear y tirar el esquema cuesta entre 13 y
20 veces lo que vaciar las filas, en las dos ejecuciones.

`DELETE …; DELETE …` en una sola sentencia **no** es una opción: asyncpg responde
`cannot insert multiple commands into a prepared statement`. De ahí la forma con CTE.

## 3. Prototipo, medido de punta a punta

Con el modelo de D1-D2 aplicado a `backend/tests/conftest.py` y **sin tocar ningún test**:

| Ejecución | Antes | Después |
|---|---|---|
| Suite completa | 618,51s · 5 329 + 35 | **165,74s** (1 fallo, ver D5) y **170,66s** (verde) · 5 329 + 35 |
| Subconjunto (properties, cleaning, auth, scheduler y los ficheros con segunda sesión) | 303,49s · 1 819 + 35 | **74,79s** · 1 819 + 35 |

Con `pytest-xdist` añadido en caliente (`uv run --with pytest-xdist`), excluyendo los tres ficheros
de ids no deterministas:

| Ejecución | Serie | `-n 4` |
|---|---|---|
| 4 678 tests | 176,69s | **55,97s** (3,16×, verde) |

Sin el sufijo por worker y sin excluir esos tres ficheros, xdist ni arranca:
`ERROR gw3 - Different tests were collected between gw0 and gw3`.

## 3 bis. La implementación, medida en una máquina ocupada (2026-08-10)

La fase 1 se implementó y midió con **otras sesiones SDD corriendo sus propios stacks y su propia
suite completa en paralelo** (cuatro proyectos de compose vivos, `load average` 16,7 sobre 12
núcleos). Eso invalida cualquier comparación contra los 618,51s de §1, que se midieron con la
máquina libre: la ejecución completa de la fase 1 dio **653,12s**, y leerlo como «no mejora» sería
leer la contención, no el cambio.

La comparación que sí vale es **A/B consecutivo sobre el mismo subconjunto y bajo la misma carga**,
alternando solo `backend/tests/conftest.py`:

| `tests/auth` (535 tests) | Tiempo |
|---|---|
| Modelo viejo (`create_all`/`drop_all` por test) | 650,06s |
| Modelo nuevo (esquema una vez + vaciado de filas) | **90,11s** |

**7,2×** sobre el mismo trabajo, la misma máquina y el mismo minuto. Es mayor que el 3,6× de §3
porque la contención castiga mucho más al modelo viejo: el DDL por test es la parte que compite por
CPU y por E/S, mientras que el cuerpo de los tests —que en la suite completa son varios miles sin
base de datos— cuesta lo mismo en los dos modelos y es lo que domina los 653s.

Consecuencia práctica, y es la razón por la que R2.1 se mide en CI y no aquí: **una cifra local solo
significa algo si se toma con la máquina libre o contra su propio control**. Las tres ejecuciones de
§4 se disparan en el runner de GitHub, que no comparte máquina con nadie más.

## 4. La parte que falta: CI (R1.1, R2.1)

Necesita el branch publicado, así que la ejecuta la implementación. Tres ejecuciones
**secuenciales** —no solapadas— sobre la misma referencia, antes y después:

```bash
gh workflow run backend-tests --ref sdd/backend-suite-runtime      # x3, esperando cada una
gh run list --workflow backend-tests --branch sdd/backend-suite-runtime --limit 3 --json databaseId
gh api /repos/autohostai-labs/AutoHostAI/actions/runs/<id>/jobs \
  --jq '.jobs[] | select(.name=="backend-tests-suite") | .steps[] | {name, started_at, completed_at}'
```

**Secuenciales por obligación, no por orden**: el workflow declara
`concurrency: backend-tests-${{ github.ref }}` con `cancel-in-progress: true`, así que tres disparos
solapados se cancelan entre sí y solo sobrevive el último. La cifra de R2.1 es la **mediana de las
tres**, y el paso que se mide es el de `pytest`.

Sí se pueden solapar **entre referencias distintas**: el grupo de concurrencia lleva `github.ref`,
así que una ejecución sobre `main` y otra sobre la rama no se cancelan. Las tandas de abajo se
hicieron así, y por eso la de la rama terminó mucho antes que la de `main`.

### Resultado (2026-08-10)

Fase 1, commit `ab71ada`. El paso medido es «Suite completa (incluye auth, RBAC y aislamiento por
tenant)», leído de `/repos/autohostai-labs/AutoHostAI/actions/runs/<id>/jobs`.

| Referencia | Ejecuciones | Mediana |
|---|---|---|
| `main` (antes) | 954s · 930s · 858s | **930s (15m 30s)** |
| `sdd/backend-suite-runtime` (fase 1) | 246s · 217s · 243s | **243s (4m 03s)** |

Ids: `main` `31397414664`, `31399030815`, `31400638035`; rama `31397418050`, `31397960091`,
`31398465326`. Las seis en verde.

**R2.1 se cumple con la fase 1 sola**: 243s frente a los 300s del objetivo, **57s de margen**, y
**3,83×** sobre la mediana de `main`. El paso dominante del workflow sigue siendo el de `pytest`,
que es lo que se buscaba: ya no lo domina el DDL por test, sino el trabajo real de los tests.

Dos cosas que la tabla dice y conviene no pasar por alto:

- Los 930s de `main` son **peores que los 618,51s locales de §1** —el runner de GitHub es más lento
  que esta máquina, la razón medida ronda 1,5×— y peores que los 15m 34s que midió el proposal el
  2026-08-09, porque la suite siguió creciendo entre medias. Esa es exactamente la deriva que R4
  quiere hacer visible en el propio check en vez de descubrirla seis días tarde.
- La dispersión de `main` (954s, 930s, 858s: **±5 %**) y la de la rama (246s, 217s, 243s: **±7 %**)
  son la razón de que R2.1 pida mediana de tres y no una sola ejecución, y la razón de que el
  presupuesto tenga dos umbrales en vez de uno.

### Fase 2 (`-n 4`), medida en local

Pendiente de medir en CI (tarea 8.1). En esta máquina, sobre la suite completa y con los recuentos
intactos (5 336 pasados + 35 omitidos, mismo motivo):

| Reparto | Ejecuciones |
|---|---|
| serie | ~190s |
| `-n 4` | **57,39s · 56,11s · 53,16s** |
| `-n 3` | 63,93s |

**3,5×** sobre la serie de la misma máquina. La proyección honesta para CI sigue siendo la de D6
—**2-2,5×**, no 3,5×— porque `ubuntu-latest` tiene 4 vCPU y ahí dentro corren también PostgreSQL y
Redis, mientras esta máquina tiene 12. La cifra que manda la pone 8.1.
