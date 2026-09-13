# Liquidaciones al propietario — operación

Esta página explica cómo operar la generación y revisión de liquidaciones de propietario.
Los criterios EARS viven en `sdd/specs/revenue-statements.md` y el contrato HTTP publicado en
`backend/openapi.json`.

## Ciclo mensual

El job `generate_owner_statements` corre el primer día de cada mes a las 02:00 UTC. Recorre
los tenants activos y sus viviendas `ACTIVE`, tomando como período el mes natural anterior.
Usa el lock mensual con TTL de seis horas y abre una unidad de trabajo por vivienda; si una
vivienda falla, el resto continúa.

La ejecución produce un statement `DRAFT` por cada hueco. Es idempotente sobre tenant,
vivienda y período: un statement existente se conserva intacto. El informe del job distingue
`created`, `skipped`, `failed`, `consolidated_count` y `currency_mismatch`.

## Generación manual

Para adelantar una liquidación, usa `POST /api/v1/owner-statements/generate` con:

```json
{"property_id": "<uuid opcional>", "period_end": "2026-07-31"}
```

`period_end` es el último día del mes a liquidar; el sistema reconstruye el mes natural
completo a partir de él, y un día que no sea el último del mes devuelve `422`. El cuerpo
no admite `period_start` ni ningún otro campo (`extra="forbid"`). Sin `property_id` se
procesan todas las viviendas activas del tenant autenticado. La respuesta son los
contadores del barrido (`created`, `skipped`, `failed`, `consolidated_count`,
`currency_mismatch`), no el statement: una repetición conserva el existente intacto y lo
cuenta como `skipped`; el detalle se consulta con `GET /api/v1/owner-statements` o
`GET /api/v1/owner-statements/{id}`.

Si el informe contiene `currency_mismatch`, corrige o retira la fila que no esté en EUR y
vuelve a ejecutar la generación. No se hace conversión de divisas ni se crea un statement
parcial.

## Aprobaciones de gastos

Un gasto que supera `TenantConfig.owner_approval_threshold_eur` se crea con una aprobación
`OwnerApproval(OTHER)` pendiente. La respuesta del propietario no muta el gasto directamente:
el job `reconcile_owner_approvals_for_expenses` corre cada cinco minutos y materializa una
aprobación o elimina un gasto rechazado que aún no esté consolidado.

Una vez asociado a un statement, el gasto no puede borrarse ni cambiar sus campos contables.
La descripción y el justificante siguen siendo editables para completar información
operativa sin alterar el snapshot.

## Revisión y estados

Consulta `GET /api/v1/owner-statements` con filtros de vivienda, período y estado. El detalle
JSON devuelve los once importes, `status` y `notes`; el desglose por reserva y la lista de
gastos consolidados se obtienen con las exportaciones (PDF y CSV) o filtrando
`GET /api/v1/expenses` por vivienda y período. El flujo legal es `DRAFT → READY → SENT`;
`SENT` es terminal. El manager puede editar notas, pero los importes y períodos solo proceden de la
generación.

## Exportaciones

- `GET /api/v1/owner-statements/{id}/export.csv` descarga solo los gastos, con seis columnas,
  UTF-8 sin BOM y una fila por gasto.
- `GET /api/v1/owner-statements/{id}/export.pdf` genera el PDF en la petición y lo devuelve
  como stream. Incluye tenant, vivienda, período, reservas, los siete buckets de gastos,
  totales y notas. El PDF no se guarda en `StorageAdapter`.

Ambas rutas requieren `READ_OWNER_STATEMENTS` y respetan el tenant de la sesión. Una descarga
no genera un `AuditLog`; las mutaciones y transiciones sí.
