# Proposal: pms-provider-decision

## Why

PRD §5.4 cierra que no se construye PMS propio y lista cuatro candidatos por prioridad — Octorate (preferente), Smoobu, Beds24, Hostaway — pero esa lista **nunca se validó contra la documentación técnica de los proveedores**: es una priorización razonable a ojo. Elegir mal no se paga en el momento sino al construir `messaging-ai`, que es la capability que sustituye el trabajo de MAGNO y la más grande del roadmap.

Tres cosas obligan a cerrarlo ahora:

1. **La mensajería es el criterio discriminante y el PRD lo deja abierto.** `PMSAdapter.get_messages()`/`send_message()` llevan un `# si soportado` (PRD §16). Aplicado en serio, ese criterio reordena la lista entera: hay proveedores sin ninguna API de mensajería y otros con la mitad rota.
2. **Booking.com ha pausado el alta de nuevos proveedores de conectividad** (*"until further notice"*, `connect.booking.com`) y Airbnb es invite-only. Pasar por un channel manager deja de ser un atajo para ahorrarse la homologación (PRD §29) y pasa a ser la única puerta abierta, lo que sube el coste de acertar.
3. **La premisa de GrinPass en PRD §5.5 no se sostiene.** Confirmado con ellos el 2026-08-02: la API REST no es pública *todavía*, pero están receptivos a nuevas integraciones. Eso es más blando que *"no ofrece API directa salvo proyectos muy grandes"*, y desactiva la compatibilidad PMS↔GrinPass como criterio de selección.

**Este change es retrospectivo**: la investigación y el ADR ya están escritos, igual que `dev-hosting-provider` produjo ADR 0001. Se registra en el flujo para que la decisión quede en `sdd/metrics.md` y sea consultable por `/sdd:history` — sin eso, dentro de seis meses nadie encuentra por qué Beds24.

Fuentes: `docs/adr/0006-pms-channel-manager-provider.md`, PRD §5.4, §5.5, §16, §22, §29.

## What changes

Tras este change existe un ADR que cierra la elección de proveedor PMS/Channel Manager con evidencia —once proveedores comparados en profundidad de API, catálogo de OTAs, disponibilidad de sandbox y precio a 2/10/50/200 unidades— y el resto de la documentación deja de contradecirlo. El PRD **no se edita**: la desviación vive en el ADR, según la convención que fijó ADR 0005. No cambia ninguna línea de código ni el comportamiento del sistema; `MockPMSAdapter` sigue siendo la única implementación hasta `pms-beds24-adapter`.

Ficheros que toca: `docs/adr/0006-pms-channel-manager-provider.md` (nuevo), `docs/README.md`, `docs/reservations.md`, `sdd/roadmap.md`, `sdd/steering/{product,architecture,backend-architecture,security}.md` y `.gitignore` (excluir el export HTML que genera el preview de Markdown sobre los ADR).

## Requirements

### R1 — La decisión de proveedor queda registrada con su evidencia

**Como** owner del producto, **quiero** que la elección de PMS/Channel Manager esté documentada con alternativas y cifras, **para** poder revisarla o revertirla sin repetir la investigación.

Acceptance criteria:

1. WHEN se consulta `docs/adr/`, THE SYSTEM SHALL contener un ADR numerado `0006` con las secciones Estado, Contexto, Decisión, Consecuencias y Alternativas rechazadas, igual que los ADR 0001-0005.
2. THE SYSTEM SHALL nombrar el proveedor elegido para el MVP y el de la fase SaaS, cada uno con su coste mensual a 2, 10, 50 y 200 unidades.
3. THE SYSTEM SHALL registrar cada alternativa rechazada con la razón objetiva que la descarta, citando la fuente.
4. THE SYSTEM SHALL declarar en Consecuencias al menos las limitaciones asumidas del proveedor elegido, no solo sus ventajas.
5. WHERE una decisión se aparta del PRD, THE SYSTEM SHALL identificar la sección concreta del PRD afectada.

### R2 — El steering deja de contradecir la decisión

**Como** agente o revisor que arranca una fase SDD, **quiero** que el steering diga la verdad sobre el proveedor y sobre la capa de accesos, **para** no heredar premisas caducadas en cada `/sdd:design`.

Acceptance criteria:

1. WHEN se carga `steering/product.md` en las fases `new` o `design`, THE SYSTEM SHALL nombrar el proveedor elegido y no presentar como candidatos vigentes los descartados.
2. WHEN se carga `steering/architecture.md` en las fases `design` o `tasks`, THE SYSTEM SHALL presentar la capa de accesos como decisión abierta y no como flujo cerrado vía PMS.
3. IF `steering/architecture.md` describe la capa de accesos, THEN THE SYSTEM SHALL conservar intactas las restricciones de PRD §5.6 que siguen vigentes: `OCCUPIED_ESTIMATED` se calcula sin sensor de puerta y nada puede requerir `DOOR_OPENED`.
4. THE SYSTEM SHALL usar en `steering/backend-architecture.md` un ejemplo de adapter coherente con el proveedor elegido.
5. WHEN `steering/backend-architecture.md` enuncia la regla de Liskov sobre `MockPMSAdapter`, THE SYSTEM SHALL enlazar el caso real que la motiva — la separación de `PMSMessagingPort`.

### R3 — El trabajo derivado queda en el roadmap

**Como** owner, **quiero** que lo que la decisión desencadena esté en la secuencia de trabajo, **para** que no se pierda entre la decisión y su implementación.

Acceptance criteria:

1. THE SYSTEM SHALL registrar en `sdd/roadmap.md` una entrada para medir empíricamente el proveedor antes de las entradas cuyo diseño depende de esa medición.
2. THE SYSTEM SHALL registrar una entrada para la integración real del adapter, situada antes de `messaging-ai`.
3. THE SYSTEM SHALL indicar en cada entrada nueva su procedencia con la nota de estilo del roadmap.
4. IF una entrada del roadmap está duplicada, THEN THE SYSTEM SHALL conservar únicamente la variante que incluye las obligaciones heredadas.

### R4 — Los ADR son descubribles desde el índice de documentación

**Como** persona que busca por qué el sistema es como es, **quiero** llegar a los ADR desde `docs/README.md`, **para** no depender de saber que el directorio existe.

Acceptance criteria:

1. WHEN se lee `docs/README.md`, THE SYSTEM SHALL describir el directorio `adr/` y su convención de nombrado.
2. THE SYSTEM SHALL enunciar ahí la convención de no editar el PRD cuando un ADR se aparta de él.

### R5 — El PRD permanece intacto

**Como** coautora del PRD, **quiero** que las desviaciones se registren fuera de mi documento, **para** conservar su autoría y que la verdad de lo construido siga viviendo en las specs.

Acceptance criteria:

1. THE SYSTEM SHALL NOT modificar `docs/AutoHostAI_PRD_v5_Claude.md` en este change.
2. WHERE el ADR se aparta del PRD, THE SYSTEM SHALL dejar constancia explícita de esa elección y de su motivo, como hace ADR 0005.

## Out of scope

- **Implementar el `Beds24Adapter`, la `PMSAdapterFactory` o la separación de `PMSMessagingPort`.** Es `pms-beds24-adapter`, que va antes de `messaging-ai`.
- **Medir el coste de créditos y la latencia de webhooks de Beds24.** Es `pms-beds24-spike`, la entrada inmediatamente posterior a esta.
- **Contratar la cuenta de Beds24 o registrarse en el staging de Channex.** Acciones comerciales del owner, no del change.
- **Decidir la capa de accesos (GrinPass, TTLock/Nuki nativo o Arrivals API).** Aplazada a propósito en la decisión 5 del ADR; tendrá su propio ADR cuando la integración aporte los datos que hoy faltan.
- **Elegir proveedor para SES.Hospedajes.** El ADR recomienda Chekin, pero PRD §17 mantiene `MockSESHospedajesAdapter` en el MVP; la contratación real es de `access-notifications`.
- **Editar el PRD.** Ver R5.
- **Actualizar `sdd/specs/reservations.md`.** Hoy dice la verdad (`MockPMSAdapter` como única implementación); deja de decirla cuando entregue `pms-beds24-adapter`, y las specs las mantiene la fase `archive` de ese change.

## Affected specs

**Ninguna.** Este change no altera el comportamiento del sistema: no toca `backend/`, `frontend/` ni `infra/`, y `MockPMSAdapter` sigue siendo la única implementación del puerto. Lo que produce son documentos de decisión y de gobierno (`docs/adr/`, `sdd/steering/`, `sdd/roadmap.md`, `docs/README.md`), que no son specs de comportamiento.

`sdd/specs/reservations.md` —cuyas líneas 105-106 declaran `PMSAdapter` con `MockPMSAdapter` como única implementación (`EXTERNAL_DEPENDENCY`)— es correcta hoy y se actualizará al archivar `pms-beds24-adapter`, no aquí.
