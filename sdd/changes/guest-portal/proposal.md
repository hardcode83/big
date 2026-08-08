# Proposal: guest-portal

## Why

El PRD define un portal web para que el huésped consulte las instrucciones de su
estancia, complete el check-in y solicite soporte sin ser un `User` del sistema ni
usar JWT. La API ya reserva los endpoints `/api/v1/guest/{checkin,incident,info}/{token}`
y el frontend reserva `/guest/[token]`, pero `auth-tenancy` excluyó explícitamente
esta identidad y no existe todavía una capability que implemente el recorrido.

El alcance se basa en el PRD v5, §§6, 7.6, 7.7, 17, 22, 23 y 24. Funcionalmente
va después de `access-notifications`, porque consume las instrucciones de acceso
que esa capability entrega y completa la vía web de recogida de datos del huésped.

## What changes

Se añadirá una vía pública y acotada por token opaco para consultar la información
de una reserva, completar los datos de check-in y abrir una incidencia de soporte.
Se implementará la página móvil `/guest/[token]`, con estados de carga, error,
éxito y traducciones ES/EN, sin incorporar al huésped al modelo `User` ni al flujo
JWT/RBAC de usuarios internos.

## Requirements

### R1 — Acceso público por token acotado

**Como** huésped con una reserva válida, **quiero** acceder al portal mediante un
token opaco asociado a mi estancia, **para** poder usarlo sin una cuenta interna
ni un JWT.

Acceptance criteria:

1. WHEN una petición llega a cualquiera de los endpoints de huésped con un token
   válido y vigente, EL SISTEMA DEBERÁ autorizar únicamente los recursos de la
   reserva y del tenant asociados a ese token.
2. IF el token es inexistente, inválido, expirado o ya consumido, EL SISTEMA DEBERÁ
   rechazar la petición con el envoltorio de error público definido por la API, sin
   revelar cuál de esas condiciones se produjo.
3. EL SISTEMA DEBERÁ almacenar únicamente una representación no reversible del
   token y NO DEBERÁ aceptar JWT ni tokens pertenecientes a otra reserva o tenant.
4. ASSUMPTION: “token de un solo uso” significa un token de acceso de una estancia
   que puede realizar el recorrido necesario del portal y queda invalidado al
   completarse el check-in; el momento exacto de consumo y el tratamiento de
   reintentos se cerrarán en design.

### R2 — Consulta de información e instrucciones

**Como** huésped autorizado, **quiero** consultar los datos operativos necesarios
para mi llegada, **para** poder encontrar la vivienda y saber cómo pedir ayuda.

Acceptance criteria:

1. WHEN el huésped consulta `GET /api/v1/guest/info/{token}`, EL SISTEMA DEBERÁ
   devolver únicamente información pública y de la estancia autorizada, incluidas
   instrucciones de llegada y soporte disponibles para esa reserva.
2. EL SISTEMA NUNCA DEBERÁ devolver JWT, credenciales internas, datos de otros
   huéspedes, notas internas, documentos completos ni secretos de almacenamiento.
3. WHEN la página `/guest/[token]` carga correctamente, EL SISTEMA DEBERÁ mostrar
   esa información en un layout mobile-first y no deberá exponer el token en
   breadcrumbs, metadata ni textos visibles.

### R3 — Check-in y datos legales del huésped

**Como** huésped, **quiero** completar el formulario de check-in, **para que** la
gestora pueda disponer de los datos necesarios para el registro legal.

Acceptance criteria:

1. WHEN el huésped solicita `GET /api/v1/guest/checkin/{token}`, EL SISTEMA DEBERÁ
   devolver el estado del check-in y solo los campos que el formulario necesita.
2. WHEN el huésped envía `POST /api/v1/guest/checkin/{token}` con datos válidos,
   EL SISTEMA DEBERÁ actualizar el Guest y la reserva asociada, avanzar el estado
   legal correspondiente y responder con un resultado sin datos sensibles
   innecesarios.
3. IF faltan campos obligatorios o un dato no cumple su formato, EL SISTEMA DEBERÁ
   rechazar la operación con errores de validación objetivos y no persistir una
   actualización parcial.
4. EL SISTEMA DEBERÁ proteger los números de documento y la demás PII sensible
   conforme a las reglas de seguridad: cifrado en reposo, ausencia del número de
   documento en listados y `AuditLog` para el acceso o modificación de sus datos.

### R4 — Soporte e incidencias desde el portal

**Como** huésped, **quiero** comunicar una incidencia durante mi estancia, **para
que** el equipo pueda atenderla sin darme acceso al backoffice.

Acceptance criteria:

1. WHEN el huésped envía `POST /api/v1/guest/incident/{token}` con una descripción
   válida, EL SISTEMA DEBERÁ crear una incidencia vinculada a la reserva y propiedad
   correctas, con `source = GUEST` y el token como referencia auditada no reversible.
2. IF el payload supera los límites configurados o no contiene una descripción
   válida, EL SISTEMA DEBERÁ rechazarlo antes de crear la incidencia.
3. EL SISTEMA NO DEBERÁ permitir al titular del token listar, modificar, asignar,
   resolver o leer incidencias más allá del acuse de la incidencia creada por ese
   envío.
4. WHEN la creación tiene éxito, EL SISTEMA DEBERÁ mostrar en `/guest/[token]` un
   acuse localizado sin revelar detalles internos de clasificación, asignación o
   tenant.

### R5 — Experiencia de portal segura y localizada

**Como** huésped en un móvil, **quiero** completar el recorrido con una interfaz
clara y accesible, **para** poder hacerlo sin conocer la aplicación interna.

Acceptance criteria:

1. WHEN se renderiza cualquier texto visible del portal, EL SISTEMA DEBERÁ
   resolverlo mediante claves presentes en los catálogos ES y EN, con idioma
   derivado de la configuración pública/cookie existente y fallback `es`.
2. EL SISTEMA DEBERÁ proporcionar estados accesibles de carga, validación, error,
   vacío y éxito, sin mostrar errores crudos del backend, trazas, tokens ni URLs
   internas.
3. EL SISTEMA DEBERÁ mantener el portal fuera de la navegación de usuarios
   autenticados y NO DEBERÁ conceder ni persistir un `User`, rol, selector de tenant
   o sesión JWT para el huésped.

## Out of scope

- Alta, login, RBAC o recuperación de contraseña de usuarios internos; pertenecen a
  `auth-tenancy`, `user-management` y `auth-account-recovery`.
- Emisión y entrega de instrucciones de acceso, adapters de cerraduras,
  notificaciones y SES.Hospedajes; pertenecen a `access-notifications`.
- Portal de gestión para propietaria/manager, dashboard, limpieza, mensajería IA y
  flujo técnico de incidencias.
- Subida de fotografías o documentos desde el portal; requiere una decisión propia
  de storage, límites y validación.
- Integración real con un proveedor externo de registro legal; se consumirá la
  capacidad disponible mediante sus puertos/adapters existentes.

## Affected specs

- `sdd/specs/guest-portal.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/auth-tenancy.md` *(referencia de exclusión del huésped; no debería
  modificarse salvo que el diseño revele una contradicción)*
- `sdd/specs/frontend-foundation.md` *(la ruta `/guest/[token]` y sus reglas de
  metadata/i18n ya existen; se actualizará solo si el comportamiento implementado
  cambia ese contrato)*

## Disposición de planificación

La capability original `guest-portal` no fue implementada. Queda sustituida en el
roadmap por `guest-portal-api` y `guest-portal-web`, manteniendo esta Proposal como
trazabilidad de los requisitos del PRD y de la decisión original. El lifecycle del
token se decidirá en `guest-portal-api`, porque afecta a la autorización, la
persistencia y la idempotencia del backend.
