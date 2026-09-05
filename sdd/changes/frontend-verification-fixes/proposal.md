# Proposal: frontend-verification-fixes

## Why

La entrada de roadmap agrupó tres hallazgos de la verificación manual de `blocked-transitions-web`
(2026-08-28/29) — nota larga en [`sdd/roadmap/frontend-verification-fixes.md`](../../roadmap/frontend-verification-fixes.md).
**Dos de los tres se han medido falsos desde entonces**, y la propia entrada lo declara y ordena
re-medirlos antes de trabajarla, así que este proposal empieza por ahí:

- **Hallazgo 2 (hidratación en headless)** — re-medido dos veces después del hallazgo y con detalle
  fechado en `sdd/project.md`: `tech-app` el 2026-08-29 (`PORT_OFFSET=10`, login real, ciclo entero
  de una incidencia, dos subidas `multipart`, a 360×780 con Playwright) y `guest-portal-messaging`
  el 2026-08-30 (`PORT_OFFSET=41`, pasada manual entera con `next dev` y sin `allowedDevOrigins`).
  Queda una re-medición propia por hacer, no un defecto por arreglar (R3).
- **Hallazgo 1 (`sdd/project.md` diagnostica mal)** — el párrafo **ya se reescribió** y hoy sostiene
  las dos medidas contradictorias a la vez, más un arreglo de fondo cuyo efecto nadie ha medido
  («el arreglo de verdad sigue siendo declarar `allowedDevOrigins`»; verificado hoy: `next.config.ts`
  no lo declara). Lo que queda es que el lector tiene que reconciliar dos afirmaciones opuestas para
  decidir qué hacer, y eso ya aparcó comprobaciones visuales en más de un change (R3, R4).
- **Hallazgo 3 (card a medio traducir)** — **vivo y confirmado en el código**. Es el trabajo real de
  este change (R1, R2).

El defecto 3 medido hoy: el backend compone **seis vocabularios** en el `preferred_language` de la
**fila** del usuario (`backend/app/dashboard/domain/labels.py`: `CLEANING_STATUS_LABELS`,
`NEXT_ACTION_LABELS`, `RESPONSIBLE_LABELS`, `INCIDENT_TITLE_LABELS`, `ACCESS_STATUS_LABELS`,
`APPROVAL_LABELS`) más los 47 `TimelineEventType` de `backend/app/timeline/domain/rendering.py`,
mientras el conmutador del topbar (`frontend/features/shell/components/locale-switcher.tsx`) sólo
cambia i18next, el cookie y `<html lang>`. Con la UI en inglés una card enseña «Open incidents»
junto a «Asignar limpiadora» y «Se requiere la aprobación del propietario». El conmutador promete
algo que no cumple, contra el principio 2 de `steering/product.md` («el dashboard responde en <10 s»):
media pantalla en el idioma equivocado no se lee en diez segundos.

Y hay un segundo mecanismo que lo perpetúa aunque se arregle el primero: las claves de TanStack
Query no llevan el locale (`dashboardKeys.cards(tenantId)`, `features/dashboard/hooks/use-dashboard-data.ts:47`),
así que el caché seguiría sirviendo el texto compuesto del idioma anterior.

## What changes

El idioma del texto que el backend compone pasa a ser **el que el cliente pide**, no el que guarda la
fila: el `ApiClient` manda el idioma activo de i18next en cada petición autenticada, y
`get_authenticated_request` lo respeta degradando a `users.preferred_language` y luego a `es`. Las
claves de TanStack Query llevan el locale en su `scope`, de modo que un cambio de idioma re-pide el
texto compuesto en vez de servir el viejo. Y el párrafo de hidratación de `sdd/project.md` se cierra
con una medición propia: una pasada headless en este worktree cuyo veredicto se registra, y un
párrafo que a partir de ahí dice una sola cosa.

Esto **reabre deliberadamente la decisión D3 de `dashboard-api`**, que rechazó `Accept-Language`
citando PRD:205 («idioma del dashboard: preferencia del usuario autenticado»). El argumento para
reabrirla: PRD:205 fija el **defecto** —de qué idioma se parte cuando el cliente no dice nada—, no
prohíbe que el lector cambie de idioma en caliente; y `frontend-foundation.md:51` obliga a que exista
el conmutador, así que las dos reglas sólo son compatibles si el idioma pedido gana sobre el
almacenado. La alternativa (que el conmutador escriba `preferred_language`) queda en Out of scope con
su motivo.

## Requirements

### R1 — El texto compuesto llega en el idioma activo de la interfaz

**As a** manager que trabaja con la interfaz en inglés, **I want** que las etiquetas que compone el
backend lleguen también en inglés, **so that** el conmutador de idioma cambie la pantalla entera y no
la mitad.

Acceptance criteria:

1. WHEN una petición autenticada declara un idioma soportado (`es` | `en`), THE SYSTEM SHALL componer
   en ese idioma todo el texto legible que hoy compone: los seis catálogos de
   `app/dashboard/domain/labels.py`, el `title` de las entradas de timeline y las etiquetas de evento.
2. IF la petición no declara idioma, THEN THE SYSTEM SHALL componer en `users.preferred_language`,
   exactamente como hoy.
3. IF la petición declara un idioma no soportado —cualquier valor que `Locale.resolve` no reconozca,
   incluido un `Accept-Language` con lista de calidades o un `es-ES`—, THEN THE SYSTEM SHALL degradar
   a `users.preferred_language` y, si ese tampoco lo es, a `es`; nunca fallar la petición.
4. WHEN el frontend emite una petición autenticada, THE SYSTEM SHALL incluir el idioma resuelto de
   i18next (`i18n.resolvedLanguage`) en ella, para todas las llamadas que pasan por el `ApiClient`.
5. THE SYSTEM SHALL leer el idioma pedido **sin declararlo como parámetro de operación**, de modo que
   `backend/openapi.json` no crezca un parámetro por ruta y `frontend/lib/api/generated/` no cambie
   por este motivo. La dependencia ya tiene el `Request` en la mano
   (`backend/app/auth/api/dependencies.py:404`), así que esto no cuesta plumbing nuevo.
6. THE SYSTEM SHALL seguir entregando `description` **sin traducir** y los literales canónicos
   (`operational_state`, `event_type`, `actor_type`, `severity`) **sin traducir**: R1 cambia de dónde
   sale el locale, no qué se traduce.
7. THE SYSTEM SHALL conservar la columna `title` almacenada sin modificarla, como copia de auditoría
   en inglés.
8. A test SHALL fallar si un endpoint que compone texto sirve un idioma distinto del que la petición
   declaró, cubriendo las cuatro combinaciones idioma-pedido × idioma-de-la-fila (`es`/`en` × `es`/`en`).
9. THE SYSTEM SHALL corregir la prosa viva que hoy afirma lo contrario de lo que R1 hace, en **las
   cuatro** casas que el design midió (OQ3 del gate, 2026-09-05): `docs/dashboard.md:43-45` —cuyo
   epígrafe «El idioma sale del usuario, no de `Accept-Language`» es exactamente lo que R1
   invierte—, `sdd/roadmap/timeline-web.md:70`, `sdd/specs/dashboard-api.md:487` y
   `sdd/specs/revenue-statements.md:306`, cuya frase «ni mecanismo de traducción por
   `Accept-Language` o locale de usuario en el backend de este proyecto» ya es falsa hoy y R1 la
   deja más falsa. Los `SHALL` de `sdd/specs/` que R1 enmienda los reescribe `/sdd:archive`; esto
   son las líneas de prosa que quedan fuera de esa reescritura.

### R2 — El caché no sirve el idioma anterior

**As a** usuario que pulsa el conmutador, **I want** que el texto compuesto se re-pida, **so that** no
me quede una card en el idioma de antes hasta que expire el caché.

Acceptance criteria:

1. WHEN se construye la clave de una consulta cuyo cuerpo contiene texto compuesto por el backend,
   THE SYSTEM SHALL incluir el locale activo en el `scope` de la clave, manteniendo la forma
   `['tenant', tenantId, resource, ...scope]` que `frontend-foundation.md:56` exige.
2. WHEN el usuario cambia de idioma, THE SYSTEM SHALL hacer que la siguiente pintura de las
   superficies afectadas —card del dashboard, detalle de propiedad y timeline— muestre el texto
   compuesto en el idioma nuevo sin recarga manual del navegador.
3. THE SYSTEM SHALL conservar el orden que `frontend-foundation.md:51` fija para el conmutador
   (`i18n.changeLanguage` → escritura del cookie → `router.refresh()`, en ese orden, sin `await` ni
   paralelismo): R2 no lo reordena ni intercala una escritura de red entre esos tres pasos.
4. A test SHALL fallar si una clave de consulta de una superficie con texto compuesto omite el locale.

### R3 — La hidratación en headless queda medida, con veredicto registrado

**As a** quien vaya a montar la suite E2E de `hardening-release`, **I want** un veredicto medido y
fechado sobre si un navegador headless conduce la app, **so that** no vuelva a planificarse sobre un
hallazgo que dos changes ya contradijeron.

Acceptance criteria:

1. THE SYSTEM SHALL registrar **una** pasada headless propia hecha en este worktree, declarando:
   driver usado, `PORT_OFFSET`, si fue contra `next dev` o contra el build de producción, errores de
   consola, si aparecen claves `__react*` en el documento, y si un clic en el conmutador de idioma
   muta el DOM.
2. IF la hidratación se completa, THEN THE SYSTEM SHALL declararlo como medido con su fecha y el
   hallazgo 2 SHALL quedar cerrado como falso en la prosa viva (`sdd/project.md`, `sdd/roadmap.md` y
   `sdd/roadmap/frontend-verification-fixes.md`).
3. IF la hidratación no se completa, THEN THE SYSTEM SHALL registrar la condición exacta bajo la que
   falla y SHALL NOT atribuirla a una causa que la pasada no haya medido.
4. THE SYSTEM SHALL usar esa misma pasada para verificar R1 y R2 a mano en las cuatro combinaciones
   rol × idioma, que es lo que el hallazgo 3 usó para demostrarse.

### R4 — El párrafo de hidratación de `sdd/project.md` deja de contradecirse

**As a** persona que va a verificar una pantalla en un worktree, **I want** una sola instrucción
operativa, **so that** no gaste una pasada de verificación mal enfocada ni cite el aviso para no mirar.

Acceptance criteria:

1. THE SYSTEM SHALL dejar el párrafo diciendo, en un solo sitio: qué probar primero, qué hacer si eso
   falla, y la fecha y las condiciones de la medición más reciente.
2. THE SYSTEM SHALL NOT dejar en él ningún arreglo propuesto cuyo efecto no se haya medido. Para
   `allowedDevOrigins` eso significa una de dos: declararlo en `frontend/next.config.ts` y registrar
   qué cambió, o dejarlo escrito explícitamente como hipótesis no verificada.
3. THE SYSTEM SHALL conservar el aviso de las credenciales en la URL — que `login-form.tsx` sin
   hidratar hace un GET con `email` y `password` como parámetros de consulta —, porque es
   consecuencia del síntoma y no del diagnóstico, y sigue siendo cierto.
4. THE SYSTEM SHALL corregir la redacción vieja en **las tres** casas vivas del hallazgo de
   hidratación (`sdd/project.md`, la entrada de `sdd/roadmap.md`, la nota
   `sdd/roadmap/frontend-verification-fixes.md`), no sólo en la primera. Los
   `sdd/changes/archive/**` que la citan son registros históricos y SHALL NOT reescribirse.
   Las **otras cuatro** casas que el design encontró son de la redacción del hallazgo 3 y no de
   éste, así que las gobierna R1.9: entre las dos, el change corrige siete.

## Out of scope

- **Que el conmutador escriba `preferred_language` del usuario** (`PATCH /users/me` self-service, sin
  `MANAGE_USERS`). Es la alternativa considerada y descartada aquí: cuesta endpoint nuevo, decisión
  de permisos, el caso sin sesión (landing y `/login` no tienen usuario) y el de un dispositivo
  compartido, y no hace falta para cerrar el defecto. Si se quiere la preferencia duradera entre
  dispositivos, es una entrada de roadmap propia, emparentada con `user-management`.
- **Retirar el conmutador de idioma**, la otra salida que la nota planteaba: `frontend-foundation.md:51`
  lo exige y la landing pública lo necesita antes de haber sesión.
- **Traducir `description`** y los literales canónicos: `dashboard-api.md` los declara sin traducir a
  propósito y este change no lo toca.
- **El idioma de las respuestas al huésped** (PRD:204, `Reservation`/`Guest.preferred_language`): es
  otro eje, detectado por reserva, y no pasa por `RequestContext`.
- **La suite E2E de Playwright**: R3 mide si el navegador headless conduce la app; montar la suite es
  de `hardening-release`.
- **El idioma de notificaciones y correos**: ningún escritor de esos pasa hoy por los catálogos que R1
  toca.
- **`incident-status-tone`, `shared-datetime-formatter`, `reservations-identity-web`** y el resto de
  candidatas adyacentes del roadmap: entradas propias.

## Affected specs

- `sdd/specs/dashboard-api.md` — la sección «Textos legibles en el idioma del usuario» (`:270-307`):
  el `SHALL` de composición pasa de `preferred_language` a «el idioma que la petición declara, con
  degradación a `preferred_language` y a `es`». Es el `SHALL` que R1 enmienda.
- `sdd/specs/auth-tenancy.md` — la resolución de `RequestContext.preferred_language`.
- `sdd/specs/frontend-foundation.md` — la sección de i18n (`:50-52`): el conmutador gana el efecto
  sobre el texto compuesto remoto; y la forma de la clave de consulta (`:56`) gana el locale en su
  `scope`.
- `sdd/specs/dashboard-web-frontend.md` — **ya exige lo correcto y por eso es la prueba de que hay
  drift**: `:217-219` manda mostrar las entradas del timeline «each in the active locale», y el
  `title` compuesto por el backend hoy no lo cumple. Su `:231-233` además muestra que la etiqueta de
  tipo de evento **sí** se traduce en el frontend (`timeline.eventType.<TYPE>`), así que en esa
  pantalla conviven las dos vías. Y `:221` es el precedente exacto de R2.1: los filtros ya viajan en
  la clave de consulta para que cada combinación se cachee aparte.
- `sdd/specs/api-contract.md` — *probablemente sin cambio*: R1.5 elige explícitamente no declarar el
  idioma como parámetro de operación, así que `openapi.json` no debería moverse. Se lista para que el
  design lo confirme en vez de suponerlo.
- `sdd/specs/local-environment.md` — el entorno de worktree, si R4 acaba declarando `allowedDevOrigins`
  en `next.config.ts`.

`sdd/project.md` y `sdd/roadmap/frontend-verification-fixes.md` no son specs, pero R3 y R4 los
modifican y son el objeto de dos de los tres hallazgos.
