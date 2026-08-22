# Proposal: properties-web

## Why

`/properties` es una de las ocho rutas del shell que hoy renderizan `RoutePlaceholder`, y es la única de ellas cuyo backend está entregado, archivado y **cuyo detalle ya funciona**: `app/(workspace)/properties/[id]/page.tsx` monta `PropertyDetailView` y se llega a él desde las tarjetas del panel. Es decir, el menú «Propiedades» lleva a un cartel de obra mientras la vista de detalle a la que debería dar paso está viva.

Falta además la única pantalla desde la que se puede responder «¿qué viviendas tengo y cómo están configuradas?»: el `status` de una propiedad (`ACTIVE`/`INACTIVE`) **no aparece hoy en ninguna parte del frontend**, y los UUID de propiedad que `/reservations` y `/incidents` imprimen en crudo no tienen dónde resolverse a un nombre.

Entrada de roadmap: `properties-web` (`needs: properties-crud, frontend-auth-session · size: S · kind: feature`). Análisis largo y decisiones cerradas en `sdd/roadmap/properties-web.md`.

## What changes

Existirá `frontend/features/properties/`, una feature nueva calcada de `features/reservations/`, que sirve `/properties` como **tabla paginada de sólo lectura** sobre `GET /api/v1/properties`: seis columnas, los dos filtros que el endpoint acepta, paginación anterior/siguiente, y cada fila enlazando al detalle ya existente. El mapa de colores de estado operativo de PRD §9.1 —hoy privado dentro de `features/dashboard`— se extrae a un componente transversal que ambas pantallas consumen, en vez de duplicarse. La página deja de renderizar `RoutePlaceholder`.

No se añade ninguna ruta, ninguna clave de navegación y ninguna mutación.

## Requirements

### R1 — El listado del portfolio

**As a** propietaria o manager, **I want** ver todas mis viviendas paginadas con sus datos de registro, **so that** sepa qué tengo y pueda entrar en cualquiera sin pasar por el panel.

Acceptance criteria:

1. WHEN la operadora abre `/properties`, THE SYSTEM SHALL pedir `GET /api/v1/properties` con `page` y `per_page` y renderizar una fila por elemento de `data`.
2. THE SYSTEM SHALL pintar exactamente seis columnas por fila, en este orden: nombre, código interno, ciudad, capacidad (`max_guests`/`bedrooms`/`bathrooms`), estado operativo y situación (`status`).
3. WHEN la respuesta trae `total_pages` mayor que 1, THE SYSTEM SHALL ofrecer navegación a la página anterior y siguiente, deshabilitando cada control en el extremo correspondiente.
4. THE SYSTEM SHALL leer la paginación del sobre `{data, total, page, per_page, total_pages}` de `PropertyPageResponse`, y NEVER SHALL asumir un sobre `meta` anidado.
5. WHEN la operadora activa la fila de una propiedad, THE SYSTEM SHALL navegar a `/properties/{id}`.
6. THE SYSTEM NEVER SHALL pintar ninguno de los campos del payload que no estén en la lista de la cláusula 2 —dirección completa, `country`, `timezone`, horas por defecto, `wifi_name`, `has_wifi_password`, `pms_provider`, `pms_external_id`, `created_at`, `updated_at`—, que son datos de ficha y no de lista.

### R2 — Los dos filtros que el endpoint acepta, y sólo esos

**As a** manager, **I want** filtrar por situación y por estado operativo, **so that** pueda aislar las viviendas inactivas o las que están esperando limpieza.

Acceptance criteria:

1. THE SYSTEM SHALL ofrecer un control de filtro para `status` con sus dos valores y otro para `current_operational_state` con sus once valores, ambos con una opción «todos» que omite el parámetro de la petición.
2. WHEN la operadora cambia cualquier filtro, THE SYSTEM SHALL volver a la página 1 antes de pedir, para que no quede en una página que el nuevo conjunto filtrado no tiene.
3. THE SYSTEM SHALL emitir las claves del objeto de filtros en orden fijo, de modo que dos estados de interfaz equivalentes produzcan la misma clave de query.
4. THE SYSTEM NEVER SHALL ofrecer búsqueda por texto, ordenación elegible ni filtro por ciudad: el endpoint no los acepta y añadirlos exigiría backend nuevo.

### R3 — Los estados de la interfaz, incluido el que no debe parpadear

**As a** operadora, **I want** que la pantalla me diga qué pasa cuando no hay datos, **so that** no me quede mirando una tabla vacía sin saber si falló algo.

Acceptance criteria:

1. WHILE la petición está en vuelo, THE SYSTEM SHALL mostrar el estado de carga transversal de `components/states/`.
2. IF la respuesta es 403, THEN THE SYSTEM SHALL mostrar un estado «prohibido» localizado, distinto del error genérico.
3. IF la respuesta es 422, THEN THE SYSTEM SHALL mostrar un estado de validación localizado, y NEVER SHALL renderizar el cuerpo del error del servidor.
4. IF la respuesta es 401, THEN THE SYSTEM SHALL tratarlo como estado de carga y no como error, para no parpadear mientras corre la rotación de token.
5. IF la respuesta es 404 sobre este endpoint de lista, THEN THE SYSTEM SHALL tratarlo como error genérico.
6. WHEN `data` llega vacío, THE SYSTEM SHALL mostrar un estado vacío localizado y ofrecer reintentar en el estado de error.
7. THE SYSTEM NEVER SHALL reintentar automáticamente una respuesta 4xx.

### R4 — Un solo mapa de colores de estado operativo en el árbol

**As a** desarrollador, **I want** que el color de PRD §9.1 viva en un único sitio, **so that** las dos pantallas que lo pintan no divergan.

Acceptance criteria:

1. THE SYSTEM SHALL exponer el badge de estado operativo como componente transversal en `frontend/components/`, que posee el mapa de colores y recibe el estado y su etiqueta ya traducida.
2. THE SYSTEM SHALL tipar ese componente sobre la unión generada `components["schemas"]["PropertyOperationalState"]`, y NEVER SHALL tiparlo sobre la unión escrita a mano de `features/dashboard/data/dto.ts`.
3. WHEN se refactoriza `PropertyCard` para consumirlo, THE SYSTEM SHALL preservar literalmente las cadenas de clases Tailwind que hoy produce, de modo que `property-card.test.tsx` y `dashboard-view.test.tsx` sigan pasando sin editar sus expectativas.
4. THE SYSTEM NEVER SHALL copiar el mapa de colores a `features/properties/` ni exportar los internos de `features/dashboard` a través de su `index.ts`.

### R5 — La superficie de datos se queda donde la dejó la excepción 6

**As a** responsable de seguridad, **I want** que esta pantalla no reabra la superficie de bulto que se cerró a propósito, **so that** las instrucciones de acceso de todas las viviendas no vuelvan a viajar en una sola respuesta.

Acceptance criteria:

1. THE SYSTEM NEVER SHALL renderizar `access_notes`, `cleaning_notes` ni `emergency_notes`, que `PropertyListItemResponse` no devuelve por la excepción 6 de la regla 11 de `steering/security.md`.
2. THE SYSTEM NEVER SHALL llamar a `GET /api/v1/properties/{id}` ni a `GET /api/v1/properties/{id}/state` desde el listado para completar una fila, porque reconstruiría esa superficie y además con una llamada por fila.
3. THE SYSTEM NEVER SHALL mostrar la contraseña de WiFi en ninguna forma, ni enmascarada: `has_wifi_password` es la única señal que el contrato ofrece.
4. THE SYSTEM SHALL renderizar como texto, nunca como HTML, todo campo de origen externo que pinte: `name`, `internal_code` y la ciudad.

### R6 — Bilingüe, sin duplicar el catálogo de estados

**As a** operadora, **I want** la pantalla completa en mi idioma, **so that** ninguna cadena quede en el idioma del que la programó.

Acceptance criteria:

1. THE SYSTEM SHALL declarar un namespace `properties` en `locales/es` y `locales/en` con las cabeceras de columna, las etiquetas de los dos filtros, los controles de paginación, las dos etiquetas de `status`, el texto accesible del enlace de fila y las copias de los estados de R3.
2. THE SYSTEM SHALL registrar ese namespace en `lib/i18n/resources.ts` en sus tres puntos: el `import`, el array de namespaces y las tablas `es` y `en`.
3. THE SYSTEM SHALL reutilizar las once etiquetas de estado operativo que ya existen en el namespace `dashboard`, y NEVER SHALL crear un segundo catálogo del mismo enum.
4. THE SYSTEM NEVER SHALL dejar ninguna cadena visible escrita en el código.

## Out of scope

- **Alta y edición de propiedades** (`POST /api/v1/properties`, `PATCH /api/v1/properties/{id}`). La API las sirve, pero `CreatePropertyRequest` tiene 21 campos y dos colisiones `409` distintas, `wifi_password` es un secreto de sólo escritura sin lector, y `_reject_explicit_nulls` hace que «borrar un campo» y «no tocarlo» sean gestos distintos. Es un formulario con mapeo de errores de servidor, no una pantalla. Entrada propia si se quiere.
- **Retirar una propiedad** (`PATCH {"status": "INACTIVE"}`; no hay `DELETE` a propósito). Acción con consecuencias de auditoría y confirmación propia.
- **`GET /api/v1/properties/{id}/state`**. No aporta al listado: cada fila ya trae `current_operational_state`. Ese endpoint existe para refrescar un indicador sin repedir el agregado, que es una preocupación del detalle.
- **Añadir un bloque de ficha al detalle.** El detalle vivo es el agregado operativo de PRD §9.2 y no muestra los datos de registro. La asimetría es real, queda declarada y no se corrige aquí.
- **Búsqueda por texto, ordenación elegible y filtro por ciudad.** Requieren backend nuevo.
- **Tocar `/dashboard`** más allá de refactorizar `PropertyCard` para consumir el badge extraído (R4).

## Affected specs

- `sdd/specs/properties-crud.md` — se amplía con la superficie de frontend que consume el listado (hoy sólo documenta el backend).
- `sdd/specs/dashboard-web-frontend.md` — se anota la extracción del badge de estado operativo a `components/`, que cambia de dónde sale el color en `PropertyCard`.
- `sdd/specs/frontend-foundation.md` — se registra el namespace `properties` y el componente transversal nuevo.
