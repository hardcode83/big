# Blocked / pending — properties-web

## 1. Esta feature convierte en material el hueco de caché del logout, y el arreglo no vive aquí

- **phase**: run (panel de seguridad, secciones 2–3, 2026-08-22)
- **type**: decision
- **what & why**: el `QueryClient` es un **singleton por navegador**
  (`frontend/lib/query/query-client.ts:22-33`) y el `logout` **no lo toca**:
  `frontend/lib/auth/auth-provider.tsx:107-118` limpia `user` y los tokens, y nada
  purga la caché. Las claves llevan ámbito de tenant, así que la exposición es
  **mismo-tenant / distinto-rol**, no cruce de tenants.

  **Lo que aporta este change, y es la razón de registrarlo aquí**: `READ_PROPERTIES`
  lo tienen sólo `TENANT_OWNER` y `PROPERTY_MANAGER`
  (`backend/app/auth/domain/policy.py:266,299`) y está **negado explícitamente** a
  `CLEANER` y `TECHNICIAN` (`policy.py:327,330`), decisión razonada en
  `backend/app/cleaning/domain/read_models.py:8` — al `CLEANER` se le dice a qué piso
  ir «sin sostener `READ_PROPERTIES`». Y `PropertySummaryDto`
  (`frontend/features/properties/data/dto.ts:41-65`) deja en esa caché el **censo
  completo de la cartera**: direcciones, códigos internos y SSID de WiFi de todas las
  viviendas del tenant, en una sola entrada.

  La clase de exposición ya existía —el dashboard está gateado en el mismo permiso—,
  pero su read model **no lleva direcciones, códigos internos ni SSIDs**. Verificado en
  la revisión: **esta feature es la primera que pone eso en la caché del navegador.**

  **Escenario concreto**: mismo navegador y mismo tenant; tras el logout de un manager,
  una `CLEANER` que entra en menos de 5 minutos (`gcTime` por defecto) puede recibir
  **de caché** las direcciones, códigos internos y SSIDs de toda la cartera — justo lo
  que el backend le niega — **sin que salga ninguna petición** que el `403` pudiera
  cortar.

  **Hoy es latente**: ningún componente montaba `useProperties` cuando se revisó. Deja
  de serlo con las secciones 4–6 de este mismo change, ya escritas.

  **No se arregla en este change, y es deliberado**: el arreglo es purgar la caché en el
  logout (y ante un cambio de `user.id`/`tenant_id`), y eso vive en la superficie de
  autenticación, no en `features/properties/`. Meterlo aquí sería ampliar el alcance de
  una entrada `[FE]` de talla `S` hasta el shell de sesión.

  **Y no es la primera vez que aparece**: el `/sdd:review` de `conversations-inbox`
  levantó exactamente este hueco y lo dejó como entrada 3 de su propio `BLOCKED.md`,
  con la misma conclusión —«necesita casa propia: una entrada de roadmap o de spec
  contra la superficie de autenticación»— y sin resolver. Dos features independientes
  chocando con el mismo hueco es la evidencia de que necesita su entrada.
- **exact resume command**: decisión humana — crear la entrada de roadmap de la
  superficie de sesión (candidato de nombre: `session-cache-purge-on-logout`), y
  resolverla **junto con** la entrada 3 del `BLOCKED.md` de `conversations-inbox`, que
  es el mismo hueco visto desde otra feature. Ninguna de las dos debería cerrarse por
  separado.
