---
phases: [new, design]
---

# Product — AutoHostAI

## Qué construimos

Sistema operativo de viviendas turísticas que sustituye a la gestora externa (MAGNO): atención al huésped con IA y escalado humano, coordinación de limpiezas y mantenimiento, accesos, pricing por reglas, reporting al propietario y timeline auditable. Capa encima de un PMS externo (**Beds24**, elegido en [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md); Octorate como segunda opción, Channex en fase SaaS) — **el PMS es la fuente de verdad de reservas, calendarios y precios publicados**.

**No es**: un PMS, un Channel Manager, ni integra OTAs directamente.

## Para quién

1. **Propietaria** (2 viviendas Madrid: REDES11, PAJARITOS8): entender en <10 s qué pasa en cada vivienda desde el móvil; aprobar gastos > 100 EUR.
2. **Manager**: operar reservas, limpiezas, incidencias, conversaciones.
3. **Limpiadoras/técnicos**: recibir, aceptar y completar tareas desde el móvil con checklist y fotos.
4. Fase futura: venderse como SaaS multi-tenant.

## Principios (innegociables)

1. **Una vivienda es una máquina de estados** — estados canónicos del PRD §3.1, toda transición genera TimelineEvent auditable.
2. Dashboard responde "¿qué pasa y quién tiene la próxima acción?" en <10 segundos.
3. MVP de calidad producción end-to-end con adapters mock donde falten credenciales — nunca maqueta visual.
4. Gastos > umbral (default 100 EUR) requieren aprobación del propietario.
5. Pricing determinista por reglas; la IA explica, nunca calcula precios.
6. La IA nunca promete reembolsos, admite responsabilidad, inventa códigos/disponibilidad ni da asesoría legal (PRD §13).

## Non-goals MVP (PRD §29)

PMS/Channel Manager propio; APIs directas de Airbnb/Booking/GrinPass; scraping; submission real a SES.Hospedajes sin credenciales; app nativa; ML pricing; reembolsos automáticos; facturación fiscal; lógica basada en apertura de puerta por PIN.

## Prioridad de entrega (PRD §30)

1) Estado operacional (state machine + dashboard) → 2) timeline → 3) limpieza → 4) mantenimiento → 5) mensajería → 6) adapters PMS/acceso → 7) pricing → 8) statements. El DoD completo del MVP está en PRD §28 (20 criterios).
