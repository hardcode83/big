# auth-session-generation-semantics

[FE] **las dos grietas de `frontend/lib/auth/` que la bandeja de notificaciones destapó al ser el primer
consumidor de mutaciones optimistas del frontend.**

Encargo del `/sdd:archive` de `notifications-inbox-web` (2026-08-29), redactado en su `proposal.md`
§«Encargos a `/sdd:archive`». No se arreglaron allí porque **cambian la semántica de un módulo
compartido**, y eso no lo decide una feature de bandeja de notificaciones: `lib/auth/` lo consumen las
cinco shells, el transporte de la API y todas las mutaciones futuras.

## Los dos hechos, medidos en el run y reconfirmados por el panel de `/sdd:review`

### 1. `refresh()` purga la caché sin mover la generación de sesión

En el `catch` de `refresh()` (`frontend/features/auth/.../auth-provider.tsx`) se llama a
`purgeSessionCache()` **sola**, sin `clearSessionTokens()` y sin `notifySessionExpired()`. Como
`sessionGeneration` sólo se mueve dentro de los dos escritores de tokens (`lib/auth/session-store.ts`),
ése es el único camino de purga que la deja quieta.

Consecuencia: una mutación optimista cuyo snapshot se tomó en esa misma generación **pasa la guarda** de
`use-mark-read.ts` y reescribe las filas del usuario saliente sobre la caché recién vaciada — que es
exactamente lo que R3.4 de `notifications-inbox-web` prohíbe.

**Hoy es latente, no vivo**: ningún `useAuth()` del árbol desestructura `refresh` (los veinte sitios leen
sólo `status`, `user` y `login`). Verificado dos veces: en el run del change y de nuevo por el panel de
review.

**El arreglo bueno** es mover el incremento de generación **dentro** de `purgeSessionCache()`, para que
«toda purga invalida todo snapshot en vuelo» sea cierto por construcción y no por inspección de los
llamantes.

### 2. Limpiar tokens al expirar la sesión anula a propósito una guarda del coordinador

El listener de `subscribeToSessionExpired` llama ahora a `clearSessionTokens()`, porque una sesión
declarada expirada no debe conservar credenciales en memoria y en dos rutas
(`SessionInvalidatedError` y «No refresh token available») las conservaba. Eso **anula la guarda** de
`lib/auth/refresh-coordinator.ts:57`, que limpia tokens **sólo** si la generación no se movió.

Interleaving concreto: refresco pendiente en la generación G → el usuario vuelve a autenticarse
(`login()` escribe G+1 y espera `/auth/me`) → el refresco viejo resuelve, lanza
`SessionInvalidatedError`, y el listener tira los tokens **de la sesión nueva**; `login()` acaba poniendo
`authenticated` sobre un almacén vacío y se recupera solo en el siguiente `401`.

Se aceptó a sabiendas: antes del cambio esa misma carrera ya terminaba en `expired` —lo que se pierde es
una recuperación que nadie usaba— y la alternativa, una sesión expirada que conserva credenciales, es
peor.

**La salida** es llevar la generación **dentro** de la notificación de expiración y limpiar sólo cuando
la sesión que expira siga siendo la vigente.

## Alcance

Sólo `frontend/lib/auth/` y `frontend/features/auth/`. Sin backend, sin esquema, sin migraciones, sin
contrato de API. La verificación es la suite de frontend más tests nuevos que reproduzcan los dos
interleavings descritos arriba: hoy ninguno de los dos tiene test que falle.

## Lo que no es

- **No es un endurecimiento de la sesión** ni una revisión del refresh: la rotación de tokens, el
  coordinador y la purga siguen siendo los de `frontend-auth-session`.
- **No arregla nada que un usuario note hoy**: (1) es latente y (2) degrada a un `401` que se recupera
  solo. Es deuda de semántica que el siguiente consumidor de mutaciones optimistas volverá a pisar.
