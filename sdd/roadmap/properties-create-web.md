# properties-create-web

[FE] **alta y edición de propiedad desde `/properties`**, que hoy es sólo lectura.

> Hito «MVP operable» 3 — *autoservicio del tenant* (auditoría del 2026-09-04).

**El hecho medido (2026-09-04)**: `POST /api/v1/properties` (`backend/app/properties/api/router.py:112-161`)
y `PATCH /api/v1/properties/{id}` (:210) existen, responden `409` en colisión de `internal_code`
o `pms_external_id` (:117-123), y `frontend/features/properties/` contiene sólo `components/list/`,
`data/http/http-properties-source.ts`, `hooks/use-properties.ts` y `lib/error-mapping.ts` — ni
un `useMutation`. `properties-web` lo dejó escrito (`sdd/roadmap.md`, entrada `properties-web`:
*«Fuera de alcance: `POST` y `PATCH` —que la API sí sirve—, alta, edición y retirada desde la
web»*) sin entrada de seguimiento. Hoy una propiedad nace por `seed_demo`
(`cli/seed_demo.py:203-228`) o por `curl`.

**Por qué no es cosmético**: es la segunda mitad del onboarding del tenant. Con `/platform`
(crear tenant y usuarios) y `tenant-settings-web` (el owner crea su personal), lo único que sigue
exigiendo a un operador con terminal es dar de alta la vivienda. Para el MVP son dos `POST`; para
la demo pública y para cualquier segundo tenant es la diferencia entre «prueba el producto» y
«pídemelo por email».

**Alcance**: formulario de alta y edición sobre los campos de `CreatePropertyRequest`/`PATCH`
(`properties/api/schemas.py`): nombre, `internal_code`, dirección, capacidad, horas por defecto
de check-in/out, zona horaria, notas (ver abajo), `pms_external_id`. Para `MANAGE_PROPERTIES`
(manager; el owner es lectura, `policy.py:343-383`). Retirada (`status=INACTIVE`) si el `PATCH`
la admite. Sin backend.

**Lo que decide y no es cosmético**:

1. **Las tres notas son sumideros de la regla 11.** `access_notes`, `cleaning_notes` y
   `emergency_notes` son texto libre no denylisted (`properties-crud` design D7);
   `tech-incident-context` metió `access_notes` en el censo con la excepción 6 y las sacó del
   listado paginado; `plaintext-sink-encryption-at-rest` (pendiente) pide cifrarlas. **Este
   formulario es el primer escritor desde la UI de esas columnas.** No cambia el censo —el radio
   de lectura es el mismo—, pero el design lo cita, y la UI dice junto al campo qué **no** va ahí
   (el código de la cerradura es un `AccessRecord`, no una nota). Si el panel pide más, la
   respuesta es `plaintext-sink-encryption-at-rest`, no este change.
2. **`pms_provider` no se edita.** Es create-only por diseño (`schemas.py:134-144`: el índice
   único parcial se apoya en `coalesce(pms_provider,'MOCK')`). El formulario de alta lo puede
   ofrecer entre `{MOCK, CHANNEX, BEDS24}` con `MOCK` por defecto, o no ofrecerlo y dejar que el
   operador lo fije con el CLI cuando conecte el PMS. Recomendación MVP: **no ofrecerlo**; la
   conexión al PMS es operación con `pms_credentials` y un subcomando `assign-provider` que hoy
   no existe (`docs/pms-credentials.md:98-104`) — candidata `[BE]` `pms-provider-assign-cli`.
3. **`pms_external_id`** sí es editable y anulable (`NULLABLE_FIELDS`, :78); es el `propertyId`
   de Beds24 (`docs/beds24-adapter.md:66-69`). La UI lo etiqueta así.
4. **`wifi_password`** ya va cifrada (`wifi_password_encrypted`, regla 3); el formulario la
   escribe y nunca la lee de vuelta — comprobar que `GET` no la serializa (regla 4) antes de
   pintar un campo «actual».
5. **Zona horaria** es lo que gobierna los jobs de reloj (`state_resolution.py:40-64`); un
   valor equivocado hace check-ins a deshora. Lista de IANA, `Europe/Madrid` por defecto.

**Fuera de alcance**: conexión al PMS por UI; borrado físico; fotos de la propiedad (no hay
entidad); la rejilla con foto de `/properties` que `visual-restyle-workspace` dejó fuera.
