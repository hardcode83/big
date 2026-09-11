# revenue-pricing

`PricingRule` CRUD, la fórmula de PRD §7.17 con sus guardrails, el job diario `generate_price_recommendations` a 60 días y la aprobación/rechazo de recomendaciones. Modo 1 del PRD §19: recomienda, no publica (no está en el plan original: `revenue` se partió en tres el 2026-08-16, porque abarcaba tres dominios —pricing, statements, reviews— con módulos, entidades y APIs distintos y no cabía en un solo change)
