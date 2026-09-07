# auth-session-persistence

[FE+BE] **hacer que la sesión sobreviva a una pestaña nueva o a un reload, sin volver a
dejar el JWT en un almacenamiento que JS pueda leer.**

Registrada el 2026-09-04 a raíz de una pregunta directa sobre por qué la app pide login
otra vez al abrir una pestaña nueva o al volver a entrar. No es un bug: `frontend-auth-session`
lo especifica así a propósito (`sdd/specs/frontend-auth-session.md` líneas 31-48) —
`session-store.ts` es memoria pura, sin persistencia ni hidratación, y el `proposal.md`
de aquel change descarta explícitamente cookies `httpOnly`/BFF como fuera de alcance,
sin dar más razón que el recorte de alcance de ese change.

## Por qué se cuestiona ahora

El límite actual está motivado por seguridad (un JWT en `localStorage`/`sessionStorage`
es legible por cualquier XSS), pero el coste de UX recae sobre el perfil de usuario
equivocado para este producto: managers, cleaners y technicians abren la app varias
veces al día, a menudo en más de una pestaña o dispositivo móvil, y hoy cada apertura
es un login manual completo.

## El patrón que resuelve ambos lados

Refresh token en cookie `httpOnly` + `Secure` + `SameSite` (invisible a JS, por tanto
inmune al mismo vector de robo que memoria-pura ya evita) y access token de vida corta
en memoria, igual que hoy. Un reload o pestaña nueva puede intentar un refresh silencioso
contra `/api/v1/auth/refresh` leyendo la cookie, sin que el frontend maneje el refresh
token directamente en ningún momento.

## Lo que toca (medido, no supuesto)

- **Backend** (`backend/app/auth/`): hoy `POST /auth/login` devuelve `refresh_token` en
  el body (`schemas.py:115`) y `POST /auth/refresh` lo exige en el body de la request
  (`schemas.py:26`, `router.py:86`) — no existe ninguna ruta de cookie. Cambiar el
  transporte a `Set-Cookie`/lectura de cookie en ambos endpoints, decidir rotación y
  expiración de la cookie, y qué pasa con clientes no-browser si los hay.
- **Frontend** (`frontend/lib/auth/`): `session-store.ts` deja de guardar el refresh
  token (solo el access token en memoria); `auth-provider.tsx` gana un intento de
  refresh silencioso al montar, antes de decidir `anonymous` vs `authenticated`;
  `refresh-coordinator.ts` y las dos grietas de `auth-session-generation-semantics`
  hay que revisarlas contra el nuevo flujo de arranque, no asumir que siguen aplicando
  igual.
- **CORS/infra**: cookies cross-origin entre `frontend` y `backend` en dev/prod
  (`credentials: include`, `SameSite`, dominio de la cookie) — verificar contra
  `ingress-https-hardening`/`tunnel-host-surface-hardening` antes de diseñar.

## Lo que no es

- No es un endurecimiento adicional de sesión ni toca RBAC/tenant isolation.
- No resuelve `auth-session-generation-semantics` — son ejes distintos (persistencia
  vs. condiciones de carrera en purga/generación) y esta entrada puede volver a
  destaparlas en el nuevo flujo de arranque; revisar ambas notas juntas al diseñar.
