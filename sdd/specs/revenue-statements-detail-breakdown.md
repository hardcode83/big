# Desglose del detalle de liquidación (`revenue-statements-detail-breakdown`)

## Purpose

El detalle HTTP de una liquidación publica el resumen financiero y las filas que lo
componen para que clientes autorizados puedan renderizar reporting sin consultar rutas
paralelas. La composición reutiliza el caso de uso existente y mantiene separado el
contrato paginado y el de mutación.

## Requirements

### Respuesta enriquecida del detalle

- WHEN un usuario autorizado solicita `GET /api/v1/owner-statements/{statement_id}`, THE
  SYSTEM SHALL devolver los campos actuales de `OwnerStatementResponse` al mismo nivel y,
  adicionalmente, `expenses` y `reservations`.
- THE SYSTEM SHALL serializar cada reserva con sólo `id`, `check_in_date`, `nights`,
  `gross_amount`, `ota_commission`, `net_amount` y `currency`.
- THE SYSTEM SHALL serializar cada gasto con sólo `id`, `category`, `description`,
  `amount`, `currency` y `date`.
- THE SYSTEM SHALL conservar los valores financieros y temporales de las entidades ya
  compuestas, sin recalcularlos en la capa API.

### Composición y separación de contratos

- WHEN se construye el detalle, THE SYSTEM SHALL consumir las claves `statement`,
  `expenses` y `reservations` devueltas por `GetOwnerStatementUseCase`, sin añadir queries
  paralelas ni duplicar sus filtros.
- THE SYSTEM SHALL usar `OwnerStatementDetailResponse` sólo para el GET detail; el listado
  SHALL mantener `OwnerStatementPageResponse` con elementos `OwnerStatementResponse`, y
  PATCH SHALL mantener `OwnerStatementResponse`.
- THE SYSTEM SHALL mantener sin cambios los endpoints, permisos y coste de composición del
  listado y de las mutaciones.

### Tenancy y errores

- WHEN se solicita el detalle, THE SYSTEM SHALL derivar el tenant de la sesión y aplicar
  las guardas existentes a la liquidación y a sus colecciones asociadas.
- IF el identificador no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL responder
  `404` con el cuerpo constante actual y no consultar ni publicar colecciones asociadas.
- THE SYSTEM SHALL no exponer `tenant_id`, PII, notas internas, estados operativos,
  identificadores externos, datos de aprobación, claves de almacenamiento ni timestamps
  innecesarios en las proyecciones de breakdown.

### Contratos derivados

- WHEN se regenera OpenAPI, THE SYSTEM SHALL documentar el response enriquecido sólo para
  el `200` del GET detail, manteniendo las referencias existentes del listado y PATCH.
- THE SYSTEM SHALL mantener sincronizados `backend/openapi.json` y
  `frontend/lib/api/generated/openapi.d.ts` con el contrato servido.

## Key files

- `backend/app/statements/api/schemas.py` — `OwnerStatementDetailResponse` y las
  proyecciones mínimas de reservas y gastos.
- `backend/app/statements/api/router.py` — serialización exclusiva del GET detail.
- `backend/app/statements/application/use_cases.py` — composición reutilizada.
- `backend/openapi.json` — contrato derivado del backend.
- `frontend/lib/api/generated/openapi.d.ts` — tipos derivados del frontend.
- `backend/tests/statements/test_detail_schemas.py` y `backend/tests/statements/test_api.py`
  — cobertura de proyección, compatibilidad, tenancy y errores.
