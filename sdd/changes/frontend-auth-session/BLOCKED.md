# Trabajo pendiente

- phase: review · type: decision · La revisión local está aprobada, pero el
  worktree contiene la implementación sin commit. `mark-ready` registra
  únicamente `git rev-parse HEAD` y certificaría `5d0831a`, que no contiene
  estos cambios. Hace falta un commit de la implementación o una decisión
  explícita sobre cómo registrar un SHA revisado antes de pasar a
  `READY_FOR_PR`; no se creó commit automáticamente.
  Resume with: `/sdd:review frontend-auth-session`
