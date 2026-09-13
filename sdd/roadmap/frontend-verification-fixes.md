# frontend-verification-fixes

Tres hallazgos de la verificación manual de `blocked-transitions-web` (2026-08-28/29). Van juntos
porque los tres los encontró la misma pasada y los tres degradan lo que una persona puede
comprobar antes de mergear; el tercero es además visible para el usuario final.

## 1 y 2. Diagnóstico de hidratación bajo `PORT_OFFSET` (headless) — [TECH]

Histórico: `sdd/project.md` atribuyó mal, en un momento dado, un fallo de hidratación en navegador
headless bajo `make up PORT_OFFSET=<n>` a `allowedDevOrigins`/origen cruzado, y por separado se
midió con dos drivers (el skill `browser-automation` y el MCP de `playwright`) que ningún navegador
headless completaba la hidratación — lo que habría bloqueado la suite de Playwright que
`hardening-release` da por hecha.

**Una sola casa para el estado y la medición vigentes**: el párrafo de hidratación de
`sdd/project.md` §Worktree bootstrap. No se repite aquí para no abrir una segunda casa del mismo
hecho — mira ahí la fecha, las condiciones y el veredicto de la medición más reciente.

## 3. La card del dashboard se queda a medio traducir — [FE]

`dashboard-api` componía `title`, `cleaning_status`, `next_action.label` y las etiquetas de evento
en el **`preferred_language` del usuario**, no en el idioma activo de la interfaz — estaba
documentado en `docs/dashboard.md`, que `frontend-verification-fixes` corrigió (§«El idioma sale de
lo que declara la petición, no de `preferred_language` a secas»).

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

---

un párrafo de `sdd/project.md` diagnosticaba mal un fallo de hidratación en navegador headless bajo `PORT_OFFSET` (histórico — ver el párrafo de hidratación de `sdd/project.md` §Worktree bootstrap para el estado y la medición vigentes, no repetido aquí) y la card del dashboard **se queda a medio traducir** porque `dashboard-api` compone en el `preferred_language` y no en el idioma de la interfaz …
