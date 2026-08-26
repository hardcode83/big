# landing-public

[FE] **la página pública de producto**, superficie que hoy no existe. Diseño en
`docs/design/2026-08-23-stitch-export/`: `landing_page_executive_emerald_style`
(escritorio, 1280 px) y `landing_page_m_vil_estilo_emerald` (móvil, 390 px).

**Entra ya por decisión de Jose (2026-08-23).** Una corrección medida sobre la premisa con
la que se decidió —«es lo que menos conflictos genera»—: al contarlos, es al revés. Es la
única de las tres entradas que **enmienda un `SHALL` normativo de una spec viva**, la
única que **cambia el punto de entrada de la app**, y la única cuyo contenido choca con
`steering/product.md`. No es un motivo para no hacerla: es lo que su `/sdd:new` tiene que
resolver, y por eso está escrito aquí en vez de descubrirse en review.

Lo que sí es cierto de la premisa, y es lo que la hace buena candidata: **no toca el
contrato de la API ni una sola pantalla existente.** Cero endpoints, cero DTOs, cero
riesgo de regresión sobre lo entregado.

## Por qué esta entrada no contradice la regla del export

La regla que gobierna el aprovechamiento del export es *«de Stitch se toma el diseño, no
los datos ni las features»* (Jose, 2026-08-23), y esta entrada **es** una superficie nueva.
La aparente contradicción se resuelve mirando qué pide cada cosa:

Las features que la regla descarta —buscador global, fotos de propiedad, rejilla de
cartera, KPIs sin dueño— son todas peticiones de **datos que el sistema no tiene**: cada
una arrastra dominio, endpoint y contrato. Esta landing no pide **ni un dato**: es
maquetación, copia y metadatos. Es, de hecho, el único sitio del export donde el diseño
*es* el entregable completo y no la piel de otra cosa.

Así que la regla no la excluye: la explica. Lo que esta entrada tiene de caro no es
producto nuevo, es (1) enmendar un `SHALL` de spec, (2) mover el punto de entrada y
(3) escribir mucha copia en dos idiomas. Tres costes conocidos y ninguno de contrato.

## Decisión 1: la variante es la pareja `executive_emerald`; la tercera se descarta

El export trae **tres** landings, y no son tres opciones equivalentes:

- `landing_page_executive_emerald_style` (1280 px) y `landing_page_m_vil_estilo_emerald`
  (390 px) son **la misma página** en dos anchos: misma copia en español, mismos cuatro
  bloques de feature (Reservas Centralizadas, Limpieza y Mantenimiento, Control de
  Incidencias, Analítica Avanzada), mismas dos métricas, misma CTA final («Comenzar
  Misión»). Son el diseño responsive, no dos diseños.
- `landing_page_mobile_autohostai` es **otra página**: copia en inglés
  («Instrumentation-Grade Property Management», «Mission control for your short-term
  rentals», «Start Free Trial») y **otro set de features** — Gestión Inteligente,
  Analítica Avanzada y *Secure Infrastructure*, que sustituye a reservas/limpieza/
  incidencias por una promesa de seguridad.

**Se implementa la pareja `executive_emerald` como un solo diseño responsive.** La tercera
se descarta como página, pero se salva una cosa de ella: el encuadre
«instrumentation-grade / mission control» es más fiel a lo que el producto es —una capa de
telemetría y operación sobre un PMS— que «plataforma todo-en-uno». Si Jose quiere ese
tono, es una decisión de copia, no de maqueta.

## Decisión 2: `/` sirve la landing al anónimo y sigue llevando al dashboard al autenticado

**Hoy `/` no es una página: es un redirect.** `app/(workspace)/page.tsx` completo:

```tsx
export default function RootPage() {
  // Stable entry redirect to the primary operational surface (design D3).
  redirect("/dashboard");
}
```

Y `(workspace)` está detrás del guard de sesión, así que la cadena actual para un visitante
anónimo es `/` → `/dashboard` → guard → `/login`. Es decir: **hoy la puerta de la casa es
el formulario de login.**

La landing tiene que ocupar `/` sin romper el hábito de quien ya trabaja aquí —Marta abre
`/` y espera su dashboard—. Lo que hay que preservar es **el destino del autenticado**, no
el fichero: `/` sirve la landing cuando no hay sesión y sigue redirigiendo a `/dashboard`
cuando la hay. Eso mueve `RootPage` de `(workspace)` a un grupo público, y el comentario
«design D3» que justifica el redirect deja de ser cierto tal cual está escrito: hay que
actualizarlo, no borrarlo.

**Reutiliza `PublicShell`, no un shell nuevo.** `features/shell/components/public-shell.tsx`
ya es un Server Component con `ShellFrame` + `Brand` + `Topbar` + `ShellFooter` +
`SkipLink` y **ya trae el conmutador de idioma como única isla cliente** — que es
exactamente el chrome que la maqueta dibuja arriba. Su docstring dice «minimal chrome for
`/login` and `/forgot-password`», así que la frase se amplía; el componente no.

Lo que la maqueta añade sobre ese chrome y hay que decidir: una barra de navegación de
marketing con `Features · Pricing · Portfolio · Team · Login · Sign Up`. De esos seis
enlaces, **cuatro no tienen destino**: no hay página de precios comerciales, ni de
portfolio, ni de equipo, y **no hay registro** —`auth-tenancy` no expone alta pública, los
usuarios los crea el tenant vía `user-management`—. Un «Sign Up» que no registra a nadie es
la clase de detalle que un panel de review marca con razón. Lo honesto es dejar los
enlaces que existen (Login) y los anclas internas de la propia página (Features), y quitar
el resto hasta que haya adónde ir.

## Decisión 3: la landing es indexable, y eso enmienda una spec viva

`sdd/specs/frontend-foundation.md:60` es un requisito normativo:

> THE SYSTEM SHALL produce localized App Router metadata from the route registry keys: a
> default title `AutoHostAI`, a `%s | AutoHostAI` template, a localized description, and
> generic Open Graph. **Every surface is `noindex, nofollow`.**

Implementado en tres sitios de `lib/metadata/create-route-metadata.ts`
(`robots: { index: false, follow: false }`) y documentado en su cabecera como invariante
del módulo.

**Una landing de marketing que no se indexa no sirve para nada**, así que este es el
conflicto real de la entrada y su `/sdd:new` tiene que resolverlo explícitamente:
`frontend-foundation` pasa de «toda superficie es `noindex`» a «toda superficie es
`noindex` **salvo** la landing pública, que es la única indexable». Escrito así —una
excepción nombrada, no un flag genérico— porque lo que ese SHALL protege sigue siendo
cierto para las otras 20 rutas: ninguna pantalla con datos de tenant, ni el portal por
token del huésped (`specs/guest-portal.md:36` insiste en `noindex/nofollow` sin canonical),
puede volverse indexable por accidente al abrir la puerta a una.

Y lo que la landing gana al ser indexable, lo tiene que pagar: es la única página del
árbol que necesita Open Graph **específico** (hoy es genérico por diseño), título propio
fuera de la plantilla `%s | AutoHostAI`, y `canonical`. Tres cosas que hoy no existen en
`create-route-metadata.ts`.

## Decisión 4: las dos métricas inventadas no se publican

La maqueta afirma **«500+ Propiedades gestionadas»** y **«99% Satisfacción de
propietarios»**. Las dos son cifras de relleno de Stitch y las dos son falsas por dos
órdenes de magnitud: `steering/product.md` dice que el usuario es *«Propietaria (2
viviendas Madrid: REDES11, PAJARITOS8)»* y que el SaaS multi-tenant es *«fase futura»*.

**Se quitan.** No es cautela de estilo: publicar una métrica de tracción inventada en la
página pública de un producto es una afirmación falsa sobre un negocio real, y además
choca de frente con el principio 3 de `steering/product.md` —*«MVP de calidad producción
end-to-end … **nunca maqueta visual**»*—, que es el principio que precisamente prohíbe
entregar apariencia sin sustancia.

El bloque de stats en sí es bueno y no hay que tirarlo: dos cifras grandes en
`JetBrains Mono` sobre cristal es de lo mejor compuesto del export. Lo que necesita es
**contenido verdadero**, y hay al menos dos candidatos que el sistema sí puede respaldar:
una cifra de operación real (eventos de timeline auditados, tareas coordinadas) o una
afirmación de producto sin número. Esa elección es de Jose y es el único input que esta
entrada necesita de él antes de arrancar.

## Decisión 5: la copia se escribe dos veces, en serio

Las tres maquetas mezclan idiomas dentro de la misma página: la de escritorio pone
`Features · Pricing · Portfolio · Team · Login · Sign Up` en inglés sobre un hero en
español, y `landing_page_mobile_autohostai` es casi entera en inglés con dos tarjetas en
español. `steering/frontend.md` no admite matices ahí: *«toda string visible pasa por
`locales/es/` y `locales/en/`; nada hardcodeado»*, y `steering/documentation.md` lo repite
como regla que genera tareas.

Consecuencia práctica que conviene ver antes de estimar: **una landing es casi toda
copia.** Es el fichero de locale más grande que va a tener el proyecto —hero, cuatro
features con título y cuerpo, stats, CTA final, footer con cuatro enlaces— y hay que
escribirlo entero en dos idiomas, con calidad de marketing en los dos. El namespace nuevo
(`locales/{es,en}/landing.json`) es el trabajo, no un trámite; el layout es lo fácil.

## Riesgo: `noindex` es un interruptor con consecuencias fuera del repo

Todo lo demás en esta entrada es reversible con un revert. El `noindex` no del todo: en
cuanto la página se indexa, existe fuera y puede quedar en caché o en resultados aunque
después se retire. Es la única parte de la entrada que hay que tratar como publicación y
no como despliegue, y el momento de decidirla es antes de mergear, no después.
