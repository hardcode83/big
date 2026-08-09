# Sesión de autenticación del frontend

Esta capability conecta el frontend con los endpoints de autenticación del
backend. La especificación EARS y sus decisiones viven en la
[propuesta del change](../sdd/changes/frontend-auth-session/proposal.md); esta
página describe el uso y los límites operativos.

## Uso

1. Abre `/login` e introduce el correo electrónico y la contraseña.
2. Tras un login correcto, el frontend carga `/auth/me` y usa la identidad,
   el rol y el tenant para el contexto de la interfaz.
3. Las superficies de workspace, cleaner y technician redirigen a `/login`
   cuando no hay sesión. La ruta interna de origen se conserva de forma segura.
4. Cerrar sesión llama a `/auth/logout` cuando es posible, elimina la sesión
   local y vuelve a `/login`.

## Sesión efímera y refresh

Los access y refresh JWT viven únicamente en memoria dentro del runtime del
navegador. Las peticiones autenticadas que reciben `401` pueden ejecutar un
único refresh coordinado y reintentar una vez la petición original. Login,
refresh, logout y peticiones sin bearer quedan fuera de ese mecanismo.

Un reload completo, el cierre de la pestaña o un nuevo runtime elimina la
sesión: el usuario debe iniciar sesión de nuevo.

## Límites de seguridad

- Los guards son client-side y sirven para UX; no protegen HTML server-rendered
  ni sustituyen JWT, RBAC o tenant isolation del backend.
- No se guardan tokens ni credenciales en cookies, `localStorage`,
  `sessionStorage`, IndexedDB, Zustand ni ningún almacenamiento persistente.
- El frontend no decide permisos de negocio ni implementa aislamiento de tenant.
- Los errores del backend no se muestran directamente; los estados visibles se
  resuelven mediante el namespace `auth` en ES y EN.
- No hay BFF, middleware de autenticación ni sesión server-side en esta
  capability.
