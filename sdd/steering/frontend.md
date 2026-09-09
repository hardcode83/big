---
applies_to: ["frontend/**"]
---

# Frontend conventions — AutoHostAI

## Estructura

Next.js 14+ App Router, TypeScript **strict**. Rutas del PRD §24: app propietario/manager, `/cleaner` y `/tech` (mobile-first), `/guest/[token]` (portal por token, sin JWT).

## Patrones

- **Server state con TanStack Query v5** (claves por recurso+tenant); **Zustand solo para estado ligero de UI**. No duplicar server state en stores.
- shadcn/ui + Tailwind; diseño responsive **mobile-first** — la propietaria opera desde el móvil.
- i18n con react-i18next: toda string visible pasa por `locales/es/` y `locales/en/`; nada hardcodeado.
- Colores de estado operacional exactos del PRD §9.1 (verde/azul/amarillo/rojo/gris por estado).
- Fotos siempre vía signed URL del backend; nunca construir URLs de storage en el cliente.
- Auth: JWT en memoria + refresh; RBAC del backend decide, el frontend solo oculta.

## UI/UX baseline

- Contraste: texto contra fondo cumple WCAG AA: mínimo 4.5:1 para texto normal y 3:1 para
  texto grande, salvo que este proyecto documente explícitamente otro umbral objetivo.
- Focus visible: todo control interactivo tiene un estado de foco visible y distinguible del
  estado por defecto y hover; no se suprime `:focus-visible` sin una sustitución equivalente.
- Teclado: todo control interactivo es alcanzable y operable solo con teclado, con un orden de
  foco que sigue el orden visual y lógico.
- Interaction targets: los objetivos táctiles/de puntero miden al menos 44x44 CSS px, salvo
  que una excepción objetiva quede documentada junto al componente.
- Contenido no textual: las imágenes significativas y los controles solo de icono tienen `alt`
  o nombre accesible equivalente.
- Formularios: cada campo tiene label programático asociado; los campos requeridos, validaciones
  y mensajes de error son explícitos.

## Estados UI

Los elementos interactivos y de datos representan explícitamente loading, empty, error, disabled,
hover y focus. En operaciones transaccionales, el envío, éxito y error son observables y el
control de submit evita doble envío mientras la operación está pendiente.

## Responsive verificable

El layout declara breakpoints verificables mediante media queries o utilidades responsive de
Tailwind; no depende de un único ancho fijo. Texto y controles permanecen utilizables sin
overflow ni clipping en los anchos mínimos que este proyecto soporta, con prioridad mobile-first.

## Testing UI/UX

Los tests de cada superficie nueva verifican los estados declarados (loading, empty, error,
disabled, hover y focus), la navegación por teclado y el orden de foco, las asociaciones de
labels, el contraste de nuevas combinaciones de color/componente y la ausencia de clipping en
los breakpoints responsive. Las comprobaciones existentes viven en `frontend/test/`, los tests
de componentes junto a sus componentes y los tests de contraste en `frontend/app/` y
`frontend/test/`.

## Don'ts

- No empezar un módulo por la UI: el endpoint/API va primero (PRD §26).
- No lógica de negocio en componentes — el backend es la fuente de verdad de estados y validaciones.
