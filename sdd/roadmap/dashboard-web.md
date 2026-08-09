# dashboard-web

[FE] **el consumo real del dashboard**: escribir `HttpDashboardSource` y sustituir el mock por ella (PRD §26.15-17, §9, §24).

**Alcance reducido dos veces, y esta entrada es lo que queda**:

1. **El login y la sesión salieron a `frontend-auth-session`** el 2026-08-07 — son independientes de la API agregada y bloquean cualquier pantalla real, así que colgarlos de aquí retrasaba lo que ya se podía hacer. Ya está archivada (2026-08-08).
2. **La API agregada salió a `dashboard-api`** el 2026-08-08 — por la costura BE/FE, igual que `guest-portal-api` / `guest-portal-web`. Un change SDD tiene una rama y un `STATE.md` (regla 10 de `rules.md`: «one feature, one branch, one working directory»), así que una entrada a caballo entre backend y frontend no se puede repartir entre dos personas sin corromper la evidencia de `mark-ready`.

## Lo que falta de verdad (verificado contra el código el 2026-08-08)

**La UI ya está construida y funciona**: `dashboard-web-frontend` (archivada el 2026-08-01) entregó las property cards, el detalle y el timeline, con estados de carga, error y vacío. `/dashboard` y `/properties/[id]` son las **dos únicas rutas del frontend con contenido real** — las otras 17 son placeholders explícitos.

Lo que falta es **la fuente de datos**:

- `frontend/features/dashboard/data/index.ts:16` → `const dashboardDataSource: DashboardDataSource = new MockDashboardSource();`
- **No existe ninguna `HttpDashboardSource`** en el repositorio. Hay que escribirla contra `lib/api`.
- Los datos de hoy salen de `frontend/features/dashboard/data/mock/fixtures.ts:19`: exactamente **dos propiedades hardcodeadas** (`redes11`, `pajaritos8`), con textos fijos en español y una imagen apuntando a `https://cdn.example.invalid/`. Cualquier otro id da «not found».

El propio fichero declara la deuda y el diseño que la hace barata (`index.ts:12-14`):

> *«DEBT (dashboard-web): today it returns `MockDashboardSource`. When the aggregate dashboard backend exists, return `HttpDashboardSource` (routed through `lib/api`) here — no UI, hook, or query-key change required.»*

Y eso es literal: los hooks (`features/dashboard/hooks/use-dashboard-data.ts:53,65,78`) y las vistas dependen **sólo** de la interfaz `dashboard-source.ts:23-41`, así que el cambio de fuente **no toca ni un componente**. El `tenantId` ya sale del usuario autenticado real (`use-dashboard-data.ts:32`), no del mock. Por eso baja a `size: S`.

## Por qué está bloqueada hoy, y por qué eso ahora se ve

`dashboard-api` entrega los tres endpoints agregados que faltan. Hasta que existan, **`HttpDashboardSource` no se puede escribir**: dos de los cuatro endpoints que consulta `dto.ts:11-12` ya están servidos (`GET /api/v1/properties` y `/properties/{id}`, desde `properties-crud`), pero `/properties/{id}/dashboard` y `/timeline/{property_id}` no existen.

Antes del split ese bloqueo era **invisible**: la entrada aparecía en la frontera del roadmap como atacable ya. Con `needs: dashboard-api` declarado, el grafo lo muestra.

## Contrato: ya está congelado, y hay un test que lo vigila

No hay que negociar formas al llegar. `frontend/features/dashboard/data/dto.ts` replica el contrato de PRD §23 (sobre de paginación, sobre de error, fechas ISO-8601 UTC) y `frontend/features/dashboard/data/boundary.test.ts` guarda la frontera. `MockDashboardSource` ya simula el sobre §23 y lanza `ApiError` reales, así que la sustitución se hace **contra un contrato que la UI ya ejercita**.

El cliente tipado existe y está al día: `frontend/lib/api/generated/openapi.d.ts` se genera desde `backend/openapi.json` (`frontend/scripts/generate-api-types.mjs:10`) y la CI lo verifica. Los tipos de los endpoints nuevos aparecerán ahí solos en cuanto `dashboard-api` regenere el contrato.

## Renombrado pendiente por el split

`frontend/features/dashboard/data/dashboard-source.ts:12` dice *«when dashboard-web (backend) ships it is replaced by an HTTP implementation»*. Tras el split eso es doblemente equívoco: quien entrega el backend es `dashboard-api`, y `dashboard-web` ya no es «(backend)». Se corrige aquí, en el mismo diff que sustituye el mock. Las demás menciones a `dashboard-web` en `frontend/features/dashboard/data/` (`index.ts:12`, `dto.ts:9`, `fixtures.ts:2,6`, `mock-dashboard-source.ts:18`) **son correctas**: describen el swap del mock, que es exactamente este change.

## Dos observaciones del estado del frontend, que NO son de este change

Salieron al inspeccionar el árbol el 2026-08-08 y conviene que no se pierdan, pero ninguna la pide un requisito de aquí:

1. **La sesión no sobrevive a una recarga.** Los tokens viven sólo en memoria (`frontend/lib/auth/session-store.ts:12`) y no hay hidratación al montar, así que cada F5 devuelve al login. **Es comportamiento especificado**, no un defecto: `sdd/specs/frontend-auth-session.md:36-37` lo fija en EARS. Pero hace incómodo recorrer el producto, así que si se quiere cambiar es una entrada propia con su decisión de seguridad, no un arreglo al paso.
2. **No hay UI de cierre de sesión.** `logout()` está implementado (`frontend/lib/auth/auth-provider.tsx:127`) y **no lo llama ningún componente** — es código muerto. `sdd/specs/frontend-auth-session.md:56` describe qué debe ocurrir «cuando el usuario cierra sesión» y hoy no hay forma de que lo haga. Huele a deriva spec-vs-código; lo confirmaría un `/sdd:review`.
