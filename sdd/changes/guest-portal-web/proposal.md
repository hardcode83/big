# Proposal: guest-portal-web

## Why

El backend del portal de huésped ya está implementado y expone las cuatro rutas
anónimas definidas en [`guest-portal-api`](../../specs/guest-portal-api.md): información
de la estancia, estado y envío del check-in, e incidencias. La ruta Next.js
`/guest/[token]` existe actualmente solo como placeholder, por lo que el huésped no
puede completar el recorrido real desde un móvil.

Este change implementa la superficie web pendiente conforme al PRD v5 §§23-24 y a la
capability original `guest-portal`, reutilizando el contrato backend ya archivado y
sin crear una identidad interna ni una sesión JWT para el huésped.

## What changes

Se implementará la página mobile-first `/guest/[token]` para cargar y mostrar la
información pública de la estancia, permitir completar el formulario de check-in y
comunicar una incidencia. La interfaz consumirá las rutas guest existentes, mantendrá
el token fuera del contenido visible y de la metadata, resolverá todas las cadenas
mediante los catálogos ES/EN y ofrecerá estados accesibles de carga, validación, error,
vacío y éxito.

## Requirements

### R1 — Acceso y presentación segura de la estancia

**Como** huésped con un enlace válido, **quiero** abrir el portal y consultar las
instrucciones de mi estancia, **para** saber cuándo y cómo llegar y pedir ayuda.

Acceptance criteria:

1. WHEN `/guest/[token]` se carga con un token válido, THE SYSTEM SHALL consultar
   `GET /api/v1/guest/info/{token}` y mostrar fechas, horas, vivienda, dirección,
   WiFi, instrucciones, código enmascarado y canal de soporte según el schema API.
2. IF la API responde con el `404` público uniforme `NOT_FOUND` definido por
   `guest-portal-api`, THEN THE SYSTEM SHALL mostrar un estado localizado que no
   distinga token inexistente, revocado, expirado, cancelado o perteneciente a otro
   tenant.
3. THE SYSTEM SHALL NEVER renderizar el token en texto visible, breadcrumbs, metadata,
   títulos, analytics ni mensajes de error, y SHALL keep the guest surface outside the
   authenticated user navigation.
4. WHEN un campo nullable de `StayInfoResponse` llega como `null`, THE SYSTEM SHALL
   renderizar una ausencia segura y comprensible sin mostrar `null`, `undefined` ni
   romper el layout.

### R2 — Check-in legal

**Como** huésped, **quiero** completar mis datos legales, **para** que la gestora pueda
registrar mi estancia.

Acceptance criteria:

1. WHEN el portal obtiene `GET /api/v1/guest/checkin/{token}`, THE SYSTEM SHALL consumir
   `missing_fields` con la semántica publicada por la API: son los nombres de los
   campos mínimos de PRD §17 que el backend evalúa como ausentes, nunca sus valores ni
   los datos ya aportados. THE SYSTEM SHALL mostrar el estado legal y, si presenta esos
   nombres al huésped, SHALL tratarlos únicamente como información declarada por el
   backend: no SHALL inferir desde `missing_fields` otros pasos, completitud o reglas de
   presentación no garantizadas por el backend, ni mostrar o solicitar fechas que
   pertenecen a la reserva.
2. WHEN el huésped envía el formulario completo a
   `POST /api/v1/guest/checkin/{token}`, THE SYSTEM SHALL enviar exactamente los seis
   campos del contrato y mostrar los estados `document_status` y
   `legal_registration_status` de la respuesta, sin mostrar el número de documento.
3. IF la API devuelve una validación `422`, THEN THE SYSTEM SHALL asociar los errores
   con los campos correspondientes y no mostrar el cuerpo crudo, trazas ni valores
   sensibles rechazados.
4. WHILE el envío está en curso, THE SYSTEM SHALL impedir envíos duplicados y anunciar
   el estado de progreso de forma accesible; tras éxito, SHALL permitir continuar o
   revisar el resultado sin crear una sesión de usuario.

### R3 — Comunicación de incidencias

**Como** huésped, **quiero** enviar una incidencia durante mi estancia, **para** que el
equipo pueda atenderla sin acceder al backoffice.

Acceptance criteria:

1. WHEN el huésped envía un título y una descripción válidos, THE SYSTEM SHALL llamar a
   `POST /api/v1/guest/incident/{token}` y mostrar un acuse localizado basado únicamente
   en la respuesta publicada. El acknowledgement puede contener `id`, `status` y
   `created_at`; la spec no exige mostrar el `id`, por lo que el frontend SHALL mostrar
   solo los campos de ese acuse que la UX defina, sin consumir ni presentar campos no
   publicados.
2. IF el formulario es inválido o la API responde `422`, THEN THE SYSTEM SHALL mostrar
   validación accionable sin crear una incidencia adicional ni revelar el payload crudo.
3. IF la API responde `429`, THEN THE SYSTEM SHALL indicar que debe esperar y SHALL
   evitar presentar el reintento como confirmación de que no se creó la incidencia.
4. THE SYSTEM SHALL NOT ofrecer al huésped rutas o controles para listar, leer,
   modificar, asignar, clasificar o resolver incidencias.

### R4 — Estados accesibles y localización

**Como** huésped móvil, **quiero** entender qué está ocurriendo en cada paso, **para**
completar el recorrido sin conocer la aplicación interna.

Acceptance criteria:

1. WHEN se renderiza cualquier texto visible del portal, THE SYSTEM SHALL resolverlo
   mediante i18n ES/EN. La implementación SHALL crear en ambos catálogos todas las
   claves necesarias para los textos que introduzca; no SHALL presuponer que esas claves
   ya existen, y usará `es` como fallback.
2. THE SYSTEM SHALL proporcionar estados accesibles y localizados de carga, vacío,
   error de autorización, error de validación, rate limit y éxito para cada recorrido.
3. THE SYSTEM SHALL mantener navegación mobile-first, foco y nombres accesibles para
   controles, campos, mensajes y regiones de estado.
4. THE SYSTEM SHALL mostrar los estados del backend como valores canónicos o copias
   localizadas definidas por el frontend, sin mover lógica de negocio ni de transición
   al cliente.

### R5 — Cliente y límites de seguridad

**Como** responsable del sistema, **quiero** que el portal respete el contrato de
seguridad del backend, **para** que la interfaz no cree una vía alternativa de acceso.

Acceptance criteria:

1. THE SYSTEM SHALL consumir exclusivamente las cuatro rutas anónimas del portal y no
   SHALL enviar `Authorization: Bearer` ni crear, guardar o refrescar JWT para el
   huésped.
2. THE SYSTEM SHALL consumir y renderizar únicamente los campos publicados por los
   schemas de respuesta, e ignorar cualquier campo adicional sin imponer validación
   runtime adicional salvo que el contrato existente ya la proporcione. Al enviar
   peticiones, el frontend SHALL enviar únicamente los campos permitidos por los
   request schemas, incluyendo `tenant_id`, `reservation_id` y cualquier campo
   adicional del check-in o la incidencia entre los campos que no puede enviar.
3. THE SYSTEM SHALL mapear `404`, `422` y `429` a estados de UI seguros y SHALL mapear
   `413` únicamente en las operaciones cuyo contrato API lo publique, sin exponer URLs
   internas, detalles de tenant, trazas o mensajes de infraestructura.
4. WHEN se regeneren los tipos frontend desde `backend/openapi.json`, THE SYSTEM SHALL
   mantener los tipos guest sincronizados con las respuestas nullable, enums, requests
   y códigos de error publicados.

## Out of scope

- Cambios al backend guest, emisión o revocación de tokens, persistencia, cifrado,
  auditoría, rate limiting o reglas de autorización; pertenecen a `guest-portal-api`.
- Login, registro, RBAC, recuperación de contraseña o sesión JWT para huéspedes o
  usuarios internos.
- Portal de gestión para propietarios/managers, lectura o gestión de incidencias desde
  el backoffice y clasificación técnica de incidencias.
- Entrega automática del enlace por email, WhatsApp o adapters de acceso.
- Subida de fotografías o documentos, integración directa con SES.Hospedajes y cambios
  de infraestructura o despliegue.

## Affected specs

- `sdd/specs/guest-portal.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/frontend-foundation.md` *(solo si el comportamiento implementado amplía o
  corrige el contrato existente de la ruta, metadata, shell o i18n)*

La implementación toma como dependencia contractual [`sdd/specs/guest-portal-api.md`](../../specs/guest-portal-api.md)
pero no debe modificarla salvo que el diseño descubra una contradicción objetiva.
