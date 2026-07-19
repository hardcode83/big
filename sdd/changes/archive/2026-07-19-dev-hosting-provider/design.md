# Design: dev-hosting-provider

## Context

Estado actual: `sdd/steering/infra.md` tiene una tabla de 6 criterios x 4 candidatos sin veredicto; `sdd/specs/infra-scaffold.md` documenta esa misma tabla como "pendiente"; `infra/environments/dev/README.md` dice "sin proveedor cloud elegido; sin Terraform real todavía". No existe ninguna convención de ADR en el repo (`docs/` solo tiene el PRD y `diagrams/`). Este change no toca código de aplicación ni Terraform real — su "implementación" es un documento de decisión (ADR) más la actualización de tres ficheros de texto existentes. El trabajo pesado está en la fase de investigación de mercado (R1-R3), no en el formato del entregable.

## Decisions

### D1 — Convención ADR: MADR ligero, numerado, en `docs/adr/`

**Chosen:** `docs/adr/0001-dev-hosting-provider.md` con secciones: Título, Estado (`Aceptado`/`Propuesto`/`Reemplazado`), Contexto, Decisión, Alternativas consideradas (con motivo de rechazo, una por candidato descartado), Consecuencias (positivas y negativas), Criterio de revisión (cuándo reabrir esta decisión). Formato MADR simplificado — suficientemente estándar para que cualquier futuro ADR del repo (staging/prod, elección de proveedor de IA, etc.) siga el mismo esqueleto sin adoptar herramientas externas (p. ej. `adr-tools`).

Rejected: usar una plantilla más pesada tipo Michael Nygard original con "Supuestos"/"Restricciones" como secciones separadas — añade ceremonia sin valor para un ADR de infra de este tamaño.
Rejected: no crear convención y dejar la decisión solo en `infra.md` — pierde trazabilidad de alternativas rechazadas y no es reutilizable para futuras decisiones de arquitectura.

### D2 — Rúbrica de evaluación: cualitativa por niveles, no score numérico ponderado

**Chosen:** cada candidato se puntúa por criterio con una escala cualitativa de 3 niveles (`Alto`/`Medio`/`Bajo` o equivalente según criterio, p. ej. madurez de provider Terraform: `Oficial maduro` / `Oficial parcial` / `Community` / `Ninguno`). Los criterios de peso alto — madurez Terraform, ajuste de migración Docker/`local-environment`, y compatibilidad con pipeline de GitHub Actions (R2.2) — se destacan visualmente (p. ej. negrita o columna propia) en la tabla comparativa, y la sección "Decisión" del ADR razona en prosa por qué el ganador pesa más en esos criterios aunque no gane en todos. Vendor lock-in (R2.5) se usa como criterio de desempate explícito cuando dos candidatos queden igualados en los criterios de peso alto — no entra en el mismo nivel de prioridad porque cierto lock-in es inherente a cualquier elección de proveedor. No se calcula una media ponderada numérica.

Rejected: score numérico 1-5 por criterio con media ponderada — da una falsa sensación de precisión objetiva a criterios que son en su mayoría cualitativos (p. ej. "carga operativa esperada"), y esconde el razonamiento real de la decisión detrás de una fórmula.

### D6 — Gate binario de compatibilidad antes de puntuar

**Chosen:** antes de aplicar la rúbrica de D2, se filtra la lista de candidatos con un gate binario (R2.4): queda excluido como veredicto final cualquier candidato que exija reescribir la app a un modelo propietario incompatible con los contenedores de `local-environment`, o que no permita un pipeline de GitHub Actions ejecutando `terraform plan`/`apply` de forma directa. Un candidato excluido por el gate sigue apareciendo en la tabla comparativa histórica (D4) con el motivo — no desaparece, solo no puede ganar.

Rejected: tratar estos dos requisitos como un criterio más dentro de la rúbrica ponderada de D2 — encajar con el stack Docker actual y con el pipeline de CI/CD ya confirmado (`infra.md`) no son preferencias graduales, son condiciones de partida del proyecto; mezclarlos con criterios de "más o menos" (como coste o carga operativa) permitiría que un candidato incompatible ganara solo por acumular puntos en otro sitio.

### D3 — Investigación en paralelo por modelo de despliegue, síntesis única

**Chosen:** `tasks.md` organiza la investigación en 3 tareas independientes (una por modelo de despliegue: VM, PaaS, serverless), cada una produciendo su sub-tabla de candidatos con los criterios de R2 y las capas gratuitas de R1.5 ya rellenas — verificando madurez de Terraform contra el registry oficial (`registry.terraform.io`) y la actividad reciente del repositorio del provider, no solo la documentación de marketing del proveedor. Una tarea final de síntesis consolida las 3 sub-tablas, aplica D2 y redacta el ADR con la decisión única. Kubernetes (R3) se investiga dentro de la síntesis final como comparación transversal, no como un cuarto modelo con su propia tarea completa, porque su tratamiento es "por qué no" más que una comparación de candidatos.

Rejected: una única tarea monolítica de investigación — con ~12+ candidatos distintos, sería difícil de verificar y de revisar en una sola pasada.

### D4 — Actualización de `infra.md`/spec: decisión arriba, tabla completa como histórico

**Chosen:** `sdd/steering/infra.md` gana una sección "Decisión (dev)" al principio de "Criterio de decisión de proveedor cloud" con el veredicto + enlace al ADR; la tabla comparativa existente se mantiene íntegra debajo (ampliada con todos los candidatos investigados) marcada como referencia histórica, no se borra. `sdd/specs/infra-scaffold.md` refleja el mismo cambio de estado en su sección "Herramientas confirmadas, proveedor pendiente" (pasa a "proveedor decidido para dev, staging/prod pendientes"). Mismo tratamiento en `infra/environments/dev/README.md` (su línea "Estado" deja de decir "sin proveedor elegido").

Rejected: reemplazar la tabla de `infra.md` por solo el veredicto — se pierde el trabajo de investigación de los candidatos no elegidos, que es justo lo que un ADR debe conservar.

## Changes by area

| Area | Files | Change |
|---|---|---|
| ADR (nuevo) | `docs/adr/0001-dev-hosting-provider.md` | Nuevo documento, formato D1, contenido de R1-R4 |
| Steering | `sdd/steering/infra.md` | Sección "Decisión (dev)" nueva + tabla ampliada con todos los candidatos (histórico) |
| Specs | `sdd/specs/infra-scaffold.md` | Sección proveedor: "pendiente" → "decidido para dev", enlace al ADR |
| Infra placeholder | `infra/environments/dev/README.md` | Línea "Estado" actualizada con el proveedor/modelo elegido y enlace al ADR |

## Data & interfaces

Ninguno — no hay cambios de código, esquema ni API. Este change es puramente documental.

## Risks & mitigations

- **Riesgo:** la investigación de mercado queda desactualizada rápido (precios y capas gratuitas cambian). Mitigación: el ADR incluye fecha de la investigación explícita y el "criterio de revisión" de D1 sirve también como disparador si los precios/free tier cambian materialmente, no solo si escala el negocio.
- **Riesgo:** Oracle Cloud Always Free tiene histórico de problemas de capacidad ("out of capacity") en algunas regiones para las VMs ARM Ampere gratuitas. Mitigación: el ADR debe documentar este riesgo explícitamente si Oracle resulta finalista, no solo su coste 0€.
- **Riesgo:** sobre-indexar en "gratis" y elegir un proveedor con provider de Terraform débil, contradiciendo la prioridad ya fijada en el proposal (R2.2). Mitigación: D2 obliga a razonar en prosa cuando el ganador no sea la opción más barata/gratuita.

## Open questions

Ninguna bloqueante para empezar `tasks.md` — dos decisiones de formato de bajo riesgo se confirman en la gate de abajo (rúbrica cualitativa vs. score numérico, y si incluir `infra/environments/dev/README.md` en el alcance).
