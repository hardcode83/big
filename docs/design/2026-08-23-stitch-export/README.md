# Export de diseño — Stitch, 2026-08-23

Origen: diseño hecho por Jose en [Stitch](https://stitch.withgoogle.com/) y exportado
como `vista-stich-autohostai.zip`. Se versiona aquí porque tres entradas del roadmap
lo citan como fuente (`design-system-tokens`, `landing-public`,
`visual-restyle-workspace`) y una referencia a un `.zip` en el portátil de una persona
no es verificable por nadie más.

## Qué es normativo y qué no

**`DESIGN.md` es la fuente canónica de los tokens** — paleta, escala tipográfica,
ritmo de espaciado, radios, elevación y reglas de componente. Es el artefacto que
`design-system-tokens` traduce a la capa `@theme` de Tailwind v4.

**Los `code.html` NO son código a importar.** Son maquetas de Stitch: Tailwind v3 por
CDN con un objeto `tailwind.config` en línea, iconos Material Symbols y fuentes desde
Google Fonts. El proyecto va en Tailwind v4 sin fichero de config, iconos lucide con
una unión cerrada (`NavigationIconName`) y sin `next/font`. Sirven como referencia de
estructura y de valores, no como origen de un copy-paste.

**Los datos que se ven en las maquetas no son el contrato.** Varias pantallas pintan
campos que la API no tiene; cada entrada de roadmap documenta cuáles y adónde van.

## Fidelidad, medida pantalla a pantalla

| Pantalla | Fidelidad | Qué es |
|---|---|---|
| `reservas_executive_emerald_style` | **Alta** | Hecha sobre la pantalla real. Reproduce el badge de build `0.1.0+2026-08-22.26c37c0`, el conmutador ES/EN, el set exacto de filtros y las 6 columnas. Referencia del restyle. |
| `dashboard_autohostai_emerald_style` | Media | Las property cards son datos reales de seed (PAJARITOS8, REDES11, María García) y respetan los tonos de PRD §9.1. Los 4 bloques de alrededor no tienen backend. |
| `propiedades_executive_emerald_style` | **Baja** | Contenido genérico de Stitch, no de AutoHostAI: Villa Azure / Marina District NYC, Aspen CO, USD, ★4.9, ocupación %, ingresos MTD, foto por propiedad. 4 de 6 datos no existen en el contrato. |
| `landing_page_executive_emerald_style` | n/a | Superficie nueva. Variante de escritorio, copia en ES. |
| `landing_page_m_vil_estilo_emerald` | n/a | La **misma** landing en móvil (390 px). Pareja responsive de la anterior. |
| `landing_page_mobile_autohostai` | n/a | Variante **divergente**: copia en inglés y otro set de features (Secure Infrastructure en vez de Reservas/Limpieza/Incidencias). No es la pareja móvil de la de escritorio. |

## Criterio de aprovechamiento: el diseño sí, los datos y las features no

Regla fijada por Jose el 2026-08-23, y es la que gobierna las tres entradas de roadmap
que nacen de aquí: **de este export se toma el diseño — tokens, composición, estilo —, no
los datos ni las features que las maquetas insinúan.** Una maqueta no escribe el backlog.

Consecuencia práctica: varias pantallas pintan cosas que el contrato no tiene, y **la
mayoría no se convierte en entrada de roadmap**. Se registran aquí para que nadie las
redescubra dentro de seis meses como un hueco no visto:

| Lo que la maqueta pinta | Estado | Por qué |
|---|---|---|
| 3 tarjetas KPI del dashboard | **entrada `dashboard-operational-kpis`** | Pedido explícito de Jose (2026-08-23). |
| Gráfico de ocupación semanal | **entrada `dashboard-occupancy-series`** | Ídem. |
| Feed de actividad cross-propiedad | **entrada `dashboard-activity-feed`** | Ídem. |
| Buscador global de la topbar | **no registrado** | Feature nueva de tamaño L que PRD §24 no pide. Si alguien la quiere, se justifica por producto, no porque saliera en un pantallazo. |
| Foto de cabecera por propiedad | **no registrado** | `PropertySummaryDto` no tiene campo de imagen y `specs/file-storage.md` solo tiene dos consumidores. Es dominio nuevo por decoración. |
| Rejilla de tarjetas de cartera en `/properties` | **no registrado** | Otra pantalla, no el restyle de la tabla entregada, y 4 de sus 6 datos no existen. Ver `sdd/roadmap/visual-restyle-workspace.md` D3. |
| ★4.9 / ingresos MTD por vivienda | **no registrado** | Ya tienen dueño natural en `revenue-reviews` y `revenue-statements`, ambas en el roadmap desde antes de este export. |
| Sidebar plano de 6 ítems | **rechazado** | Quitaría del menú 8 pantallas entregadas e inventaría 2 rutas inexistentes. Ver `visual-restyle-workspace.md` D2. |
| «500+ propiedades», «99% satisfacción» | **rechazado** | Cifras de relleno, falsas por dos órdenes de magnitud. Ver `landing-public.md` D4. |

## Artefactos y defectos conocidos del export

- `reservas_executive_emerald_style/screen.png` **no está**: el zip la trae como 28
  bytes de texto (`<FIFE Image failed to fetch>`), no como PNG. No se ha copiado un
  fichero roto. El `code.html` de esa pantalla se lee entero y es suficiente.
- `propiedades_executive_emerald_style/screen.png` es la captura **móvil** (390 px)
  aunque su `code.html` monta el sidebar de escritorio.
- `dashboard_autohostai_emerald_style`: `<title>Dashboard - PropManage AI</title>`
  — nombre de producto ajeno — y el footer repetido 4 veces.
- Todas las pantallas: `© 2024` (el export es de 2026) y `<html class="dark">` fijo.
- `DESIGN.md` define `state-success`/`warning`/`error`/`info` pero **no define gris**,
  que es la quinta familia de PRD §9.1 y el fallback de `stateColorGroup`.
- `DESIGN.md` es **solo oscuro**: no trae ningún valor para tema claro.
