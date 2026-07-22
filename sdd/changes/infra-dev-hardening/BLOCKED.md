# BLOCKED — infra-dev-hardening

## panel · run · deferred — panel de revisión de §1-2 no ejecutado
Las secciones 1-2 (código infra: security list `dynamic`, cloud-init, `ignore_changes`) se implementaron y verificaron por `plan` (0 destroy), pero el panel de revisión (architect/security/qa + reviewers de proyecto) no se lanzó (checkpoint por longitud de sesión).
**Resume:** `/sdd:review infra-dev-hardening` (cubre a escala feature todo lo implementado) antes de `/sdd:archive`.

## resto · run · deferred — secciones 3-8 pendientes
Pendiente de implementar: §3 budget €1 (código + borrar budget manual en consola), §4 Vault (código + subir secret out-of-band OCI CLI), §5 workflow apply hardening (código) + configurar Environment `dev-apply` en Settings, §6 IAM (admin de tenancy) + versioning del bucket, §7 RUNBOOK.md, §8 verificación (apply vía pipeline). Varias son operaciones OCI/GitHub que requieren tus permisos/aprobación.
**Resume:** `/sdd:run infra-dev-hardening` (continúa desde §3); coordinar contigo las partes de consola/CLI/admin.
