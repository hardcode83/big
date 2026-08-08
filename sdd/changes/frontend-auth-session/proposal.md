# Proposal: frontend-auth-session

## Why

El frontend ya dispone del shell, del transporte HTTP centralizado y de los puntos
de extensión de autenticación, pero `/login` sigue siendo un placeholder y la
aplicación no tiene contexto de sesión. Esto impide usar cualquier pantalla real
con la identidad, el rol y el tenant del usuario autenticado. La entrada del
roadmap y su análisis de partida están en
[`sdd/roadmap/frontend-auth-session.md`](../../roadmap/frontend-auth-session.md).

El backend ya expone el contrato de autenticación real (`login`, `refresh`,
`logout` y `me`) con JWT, rotación de refresh, RBAC y aislamiento por tenant; este
change conectará ese contrato con el frontend sin trasladar la autoridad de
autorización al cliente.

## What changes

El frontend tendrá una configuración pública de `apiBaseUrl`, un almacén de
sesión bajo `lib/` que mantenga access y refresh JWT exclusivamente en memoria,
un único cliente HTTP configurado con los hooks existentes y un `AuthProvider`
integrado en el orden RuntimeConfig → I18n → Auth → Query. La ruta `/login`
realizará el login y cargará la identidad mediante `/auth/me`; las rutas
protegidas ofrecerán guards client-side orientados a UX y redirección, mientras
que cada petición y decisión de autorización seguirá dependiendo del backend.

## Requirements

### R1 — Login y carga de identidad

**As a** usuario del workspace, **I want** iniciar sesión con email y contraseña,
**so that** pueda acceder a la aplicación con mi identidad real.

Acceptance criteria:

1. WHEN el usuario envía un formulario válido en `/login`, THE SYSTEM SHALL llamar
   a `POST /api/v1/auth/login` mediante el cliente HTTP centralizado y SHALL
   almacenar en memoria la respuesta de tokens sin exponer la contraseña.
2. WHEN el login responde correctamente, THE SYSTEM SHALL solicitar
   `GET /api/v1/auth/me` y SHALL exponer en el contexto de autenticación el
   identificador de usuario, rol y tenant devueltos por el backend.
3. IF el login falla, THEN THE SYSTEM SHALL mostrar un estado de error localizado,
   SHALL conservar la ruta `/login` y SHALL NOT crear una sesión autenticada.

### R2 — Sesión en memoria y refresh

**As a** aplicación frontend, **I want** renovar access tokens expirados sin
persistir credenciales en el navegador, **so that** la sesión sea usable sin
convertir el almacenamiento del cliente en una fuente persistente de tokens.

Acceptance criteria:

1. WHEN una petición autenticada elegible, enviada con un access token, recibe
   `401`, THE SYSTEM SHALL intentar una única renovación mediante
   `POST /api/v1/auth/refresh` y SHALL reintentar la petición original solo si la
   renovación tiene éxito. THE SYSTEM SHALL excluir de este mecanismo automático
   como mínimo `login`, `refresh`, `logout` cuando corresponda y cualquier
   petición enviada sin access token.
2. WHILE el runtime frontend actual permanezca activo, THE SYSTEM SHALL mantener
   access y refresh JWT únicamente en memoria. WHEN ocurre un reload completo, se
   cierra la pestaña o comienza un nuevo runtime frontend, THE SYSTEM SHALL perder
   la sesión local y requerir un nuevo login; el refresh token SHALL NOT restaurar
   la sesión después de esos eventos en este change.
3. THE SYSTEM SHALL NOT escribir tokens ni credenciales en `localStorage`,
   `sessionStorage`, cookies, IndexedDB ni ningún almacenamiento persistente del
   navegador.
4. IF el propio refresh falla, THEN THE SYSTEM SHALL limpiar la sesión en memoria
   y SHALL NOT volver a ejecutar refresh automáticamente. THE SYSTEM SHALL evitar
   bucles de refresh concurrentes y SHALL limitar cada petición original a un solo
   retry después del refresh.

### R3 — Provider y transporte autenticado

**As a** módulo frontend, **I want** consumir el contexto y transporte
autenticados desde una única integración, **so that** los módulos no implementen
su propia gestión de JWT.

Acceptance criteria:

1. WHEN `AuthProvider` se integra en `app/providers.tsx`, THE SYSTEM SHALL
   conservar el orden RuntimeConfig → I18n → Auth → Query y SHALL mantener las
   reglas de dependencias existentes entre `app`, `features`, `components` y
   `lib`.
2. WHEN el cliente HTTP envía una petición autenticada, THE SYSTEM SHALL añadir
   el access token desde el almacén en memoria mediante `getHeaders` y SHALL
   delegar los `401` en `onUnauthorized`.
3. IF no existe una sesión válida, THEN THE SYSTEM SHALL enviar peticiones sin
   credenciales de usuario y SHALL permitir que el backend determine la
   respuesta de autorización.

### R4 — Guards client-side y cierre de sesión

**As a** usuario no autenticado, **I want** recibir una redirección de UX al
intentar abrir una pantalla protegida, **so that** la interfaz no muestre
contenido operativo sin sesión.

Acceptance criteria:

1. WHEN una ruta protegida se renderiza sin sesión válida en el cliente, THE
   SYSTEM SHALL redirigir a `/login` conservando, cuando sea seguro, la intención
   de navegación para después del login.
2. WHEN un usuario autenticado cierra sesión, THE SYSTEM SHALL llamar a
   `POST /api/v1/auth/logout` cuando sea posible, limpiar el estado en memoria y
   redirigir a `/login`.
3. THE SYSTEM SHALL tratar el rol y el tenant recibidos del backend como datos de
   contexto para la UI y SHALL NOT implementar autorización de negocio, RBAC ni
   aislamiento de tenant en el frontend.
4. THE SYSTEM SHALL dejar explícito en la documentación que estos guards son de
   UX/client-side y no protegen HTML server-rendered ni sustituyen la autorización
   backend.

### R5 — Estados localizados y verificación

**As a** usuario de la aplicación, **I want** estados de autenticación claros en
ES y EN, **so that** pueda entender login, carga, refresh, expiración y errores.

Acceptance criteria:

1. WHEN se muestra cualquier estado visible de autenticación, THE SYSTEM SHALL
   resolver sus textos mediante el namespace `auth` presente en los catálogos ES
   y EN.
2. IF falta una clave del namespace `auth` en cualquiera de los locales, THEN
   THE SYSTEM SHALL fallar el test automatizado de paridad de catálogos.
3. THE SYSTEM SHALL verificar con tests los flujos de login exitoso y fallido,
   carga de identidad, refresh, logout, ausencia de persistencia y redirección
   client-side.

## Out of scope

- Cookies de autenticación, cookies `httpOnly`, `middleware.ts` de autenticación,
  Route Handlers de sesión o un BFF.
- Persistencia de tokens en `localStorage`, `sessionStorage`, IndexedDB o
  cualquier otro almacenamiento del navegador.
- Cambios en `auth-tenancy`, JWT, refresh rotation, RBAC, rate limiting o tenant
  isolation del backend.
- Autorización de negocio, ocultación como mecanismo de seguridad o enforcement
  de permisos en el frontend.
- Integración del dashboard con endpoints reales; corresponde a `dashboard-web`.
- Recuperación de contraseña; corresponde a `auth-account-recovery`.
- Una futura migración a cookies/middleware o a una sesión server-side; requerirá
  un change arquitectónico separado con sus propias decisiones, requisitos y
  revisión de seguridad.

## Affected specs

- `sdd/specs/frontend-auth-session.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/frontend-foundation.md` *(se actualizará al archivar para retirar la
  condición de autenticación “not implemented” y conservar sus límites)*
- `sdd/specs/auth-tenancy.md` *(no se modifica; se referencia como contrato del
  backend)*
