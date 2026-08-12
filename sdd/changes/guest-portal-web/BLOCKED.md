# BLOCKED — guest-portal-web

## 1. Gate operativo: retención del URI completo en el log del túnel Cloudflare de dev

- **Phase:** design (a resolver antes de `READY_FOR_PR`/ship)
- **Type:** deferred
- **What & why:** el token del portal viaja en la ruta (`/api/v1/guest/{acción}/{token}`).
  `guest-portal-api.md` (§ Deuda declarada) declara *literalmente* que confirmar la
  retención del URI completo en la cuenta del túnel Cloudflare de dev es **requisito
  previo de `guest-portal-web`**. Ningún componente del repo escribe el token en un log,
  pero al hacer el portal navegable el token empieza a viajar de verdad. No bloquea
  design/tasks/run (código frontend, no cambia la exposición); es un gate operativo antes
  del ship. No se degrada a deuda aceptada por defecto: si en el ship no se puede
  confirmar, se decide explícitamente (verificar / mitigar / aceptar con firma).
- **Resume command:** resolver antes de `/sdd:ship guest-portal-web` (verificar la política
  de logging del túnel; si no, decisión explícita registrada aquí).
