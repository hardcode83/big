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

## Don'ts

- No empezar un módulo por la UI: el endpoint/API va primero (PRD §26).
- No lógica de negocio en componentes — el backend es la fuente de verdad de estados y validaciones.
