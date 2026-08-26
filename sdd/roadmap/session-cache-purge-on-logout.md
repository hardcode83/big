# session-cache-purge-on-logout

[TECH] **La caché de consultas sobrevive al logout.** El `QueryClient` es un singleton por navegador (`frontend/lib/query/query-client.ts`) y el `logout` de `frontend/lib/auth/auth-provider.tsx` descarta los tokens y el usuario sin tocarlo. Un cambio de operador en la misma pestaña puede por tanto servir al segundo los datos cacheados del primero, **sin que salga ninguna petición** — y por tanto sin ningún 403 que pueda intervenir.

Las claves de consulta llevan ámbito de tenant (`tenantScopedKey`, que además lanza si el tenant viene vacío), así que la exposición es **mismo-tenant / distinto-rol**, no cruce de tenants. Eso acota el problema pero no lo elimina: el modelo de roles de este producto es precisamente el que separa a la propietaria y la manager de la limpiadora y el técnico.

## Por qué es entrada propia y no deuda de una feature

La levantaron **dos features independientes**, cada una desde un lado distinto, y ninguna podía cerrarla:

1. **`conversations-inbox`** (`/sdd:review`, 2026-08-22) — entrada 3 de su `BLOCKED.md`. La describió como hueco de la superficie de sesión, dejó escrito que «no lo introduce ni lo amplía este change» y concluyó que «necesita casa propia: una entrada de roadmap o de spec contra la superficie de autenticación». Sigue abierta.
2. **`properties-web`** (panel de seguridad de las secciones 2–3, 2026-08-22) — entrada 1 de su `BLOCKED.md`. Llegó a la misma conclusión sin conocer la anterior, y aportó la evidencia de permisos que le da filo.

Que dos changes que no se hablan tropiecen con lo mismo es la señal de que el hueco no pertenece a ninguno. Y hay un motivo concreto para no dejarlo en el `BLOCKED.md` de una feature: **al archivarla, la entrada se archiva con ella y el hueco desaparece del radar**.

## La evidencia de permisos, que es lo que le da filo

`READ_PROPERTIES` lo tienen **sólo** `TENANT_OWNER` (vía `_PROPERTY_READ`) y `PROPERTY_MANAGER` (vía `_PROPERTY_MANAGE`), en `backend/app/auth/domain/policy.py:266,299`. Está **negado explícitamente** a `CLEANER` y `TECHNICIAN` (`policy.py:327,330`), y la decisión está razonada en `backend/app/cleaning/domain/read_models.py:8`: a la limpiadora se le dice a qué piso ir «sin sostener `READ_PROPERTIES`». Es decir, no es un permiso que se les olvidó dar; es uno que se les quitó a propósito.

**Y `properties-web` puso en esa caché exactamente lo que ese permiso protege**: `PropertySummaryDto` deja el censo completo de la cartera —direcciones, códigos internos y SSID de WiFi de todas las viviendas del tenant— en una sola entrada. El dashboard está gateado en el mismo permiso pero su read model **no lleva** direcciones, códigos ni SSIDs, así que `properties-web` es la primera superficie que pone eso en el navegador.

**Deja de ser latente con `properties-web`.** Su `page.tsx` monta `PropertiesView` sin condición, y `READ_PROPERTIES` no está en el mapa de permisos del frontend, así que `CLEANER` y `TECHNICIAN` **pueden navegar a `/properties`**. Con petición viva el backend responde 403 y la pantalla muestra su estado «prohibido», que es lo correcto. El problema es el otro camino: servido desde caché no hay petición, así que no hay 403.

## El escenario, concreto

Mismo navegador, mismo tenant. Una manager entra, abre `/properties` y se cachea la cartera. Cierra sesión. Una limpiadora entra en la misma pestaña **antes de que pase el `gcTime`** (5 minutos por defecto) y navega a `/properties`: recibe de caché las direcciones, los códigos internos y los SSIDs de todas las viviendas — justo lo que `policy.py` le niega.

## Alcance

- Purgar la caché en el `logout` (`queryClient.clear()`), y también ante un **cambio de identidad**: no basta el logout explícito, porque un `user.id` o `tenant_id` distinto sobre la misma pestaña es el mismo problema por otro camino.
- Decidir dónde vive el gancho: el `auth-provider` es quien conoce la transición de sesión, pero el `QueryClient` lo posee `lib/query`. La costura entre los dos es la decisión de diseño real de esta entrada.
- Un test que fije la invariante: tras un logout, la caché no conserva entradas del usuario anterior.

**Lo que NO entra**: rediseñar el modelo de sesión, ni mover el JWT de memoria a otro sitio, ni tocar el mapa de permisos del frontend (que `READ_PROPERTIES` no esté ahí es una entrada distinta, si se decide que debe estarlo).

## Un paliativo que existe y por qué no sustituye a esto

El panel de seguridad de `properties-web` nombró dos atajos que cerrarían **la contribución de esa feature** sin tocar la superficie de sesión: meter `user.id` en la clave de consulta, o poner `gcTime: 0` en su hook. Se decidió no aplicarlos y dejar el hueco registrado aquí, por dos razones: no cierran la clase —la siguiente pantalla que cachee algo sensible la reabre—, y añaden código que este arreglo volvería redundante.

Si alguna vez hay urgencia de demo o de producción antes de que esta entrada llegue, el paliativo de la clave por `user.id` es el más barato y el menos invasivo.

## Metadatos propuestos

`size: S · kind: tech`

**Por qué `S`**: el arreglo son pocas líneas en la costura entre `auth-provider` y `lib/query`, más su test. Lo que no es trivial es decidir **dónde** va el gancho sin acoplar los dos módulos, y verificar que la purga cubre el cambio de identidad y no sólo el logout explícito. No toca backend, no toca contrato, no hay migración.
