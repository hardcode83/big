# frontend-verification-fixes

Tres hallazgos de la verificación manual de `blocked-transitions-web` (2026-08-28/29). Van juntos
porque los tres los encontró la misma pasada y los tres degradan lo que una persona puede
comprobar antes de mergear; el tercero es además visible para el usuario final.

## 1. `sdd/project.md` atribuye mal el fallo de hidratación — [TECH]

El documento afirma que con `make up PORT_OFFSET=<n>` la página «se sirve pero NO hidrata» porque
Next 15+ bloquea las peticiones de origen cruzado y falta `allowedDevOrigins`. **Esa causa no
sobrevive al control**: el stack del worktree principal, en `:3000`, **sin desplazamiento** y sobre
`main`, tampoco hidrata en headless — y con **cero errores de consola**. El desplazamiento de
puertos no es el diferenciador, así que la explicación que el documento da es falsa.

Cuesta tiempo real: en `blocked-transitions-web` costó una pasada entera de verificación mal
enfocada, porque el párrafo manda a descartar `PORT_OFFSET` para revisar la UI por una razón que no
se sostiene, y propone un arreglo (`allowedDevOrigins`) que probablemente no arregle nada.

Arreglar esto es **medir la causa y reescribir el párrafo**, no aplicar el arreglo que propone.

## 2. Ningún navegador headless completa la hidratación — [TECH], y es el urgente

Medido con **dos drivers independientes**: el skill `browser-automation` (patchright) y el **MCP de
`playwright`** que `sdd/project.md` lista como activado para verificación E2E. Los dos fallan
igual, tanto en `:3041` desplazado como en `:3000` sin desplazar:

- React **sí carga y arranca** — imprime su banner de DevTools a los 341 ms, así que no es que el
  JS no llegue a ejecutarse.
- Tras 30 s de espera no hay **ni un solo** elemento con claves `__react*` en todo el documento.
- Un clic en el conmutador de idioma se registra (`[active]` en el árbol de accesibilidad) y no
  cambia nada.
- El único error es el WebSocket de HMR contra `/_next/webpack-hmr`, fallando en bucle con
  `ERR_INVALID_HTTP_RESPONSE`. **Ninguna petición HTTP falla**; los 26 chunks cargan.
- En el navegador real de una persona, la misma URL hidrata perfectamente y la app es plenamente
  operable. Está verificado con capturas.

**Por qué es el urgente**: `hardening-release` da por hecho una suite de Playwright
(`npx playwright test`, ya anunciada en `sdd/project.md` §Commands). Tal y como está hoy, esa suite
no puede conducir la aplicación — no es que falle un test, es que no hay nada que pulsar.

Dos pistas para quien lo coja, ninguna confirmada:

- La ruta `webpack-hmr` con un Next que usa Turbopack sugiere desajuste entre el cliente de dev y
  el servidor. El fallo del WebSocket es el único síntoma que aparece.
- **Nadie ha probado todavía si un build de producción hidrata en headless**
  (`npm run build && npm start`). Si lo hiciera, el arreglo del E2E es correrlo contra el build en
  vez de contra `next dev`, y esta entrada se vuelve barata. **Empezar por ahí.**

## 3. La card del dashboard se queda a medio traducir — [FE]

`dashboard-api` compone `title`, `cleaning_status`, `next_action.label` y las etiquetas de evento
en el **`preferred_language` del usuario**, no en el idioma activo de la interfaz — está
documentado en `docs/dashboard.md` §«El idioma sale del usuario, no de `Accept-Language`».

Consecuencia, verificada con capturas en las cuatro combinaciones rol × idioma: con la UI en
inglés, una card enseña «Open incidents» y «Next action» junto a «Asignar limpiadora»,
«Responsible: Gestor» y «Se requiere la aprobación del propietario».

Que esté documentado no lo resuelve: el conmutador de idioma promete algo que no cumple. Decidir es
elegir una de dos — que el backend componga en el idioma que pida el cliente, o que el frontend
deje de ofrecer un conmutador que sólo cambia media pantalla.

## Lo que esta entrada NO es

No es de `blocked-transitions-web`. Ninguno de los tres lo causó ese change; los tres existían antes
y se hicieron visibles porque fue la primera vez que alguien verificó esa pantalla a mano contra un
stack real con datos. Se agrupan por petición del propietario del proyecto, no porque compartan
causa.
