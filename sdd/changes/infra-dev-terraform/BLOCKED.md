# Blocked — infra-dev-terraform

## Entry 1 — Tenancy de Oracle Cloud inexistente (prerequisito de `run`)

- **Phase**: run (anticipado desde design/proposal)
- **Type**: `decision` (needs the user — es una acción humana, no delegable a un agente: registro de cuenta, verificación de email/teléfono, elección de home region)
- **What & why**: el usuario confirmó que todavía no se ha registrado en Oracle Cloud. Ninguna task de `terraform apply` real ni de configuración de secrets de GitHub Actions puede ejecutarse ni verificarse end-to-end sin esa tenancy — está marcado como `EXTERNAL_DEPENDENCY` en la propuesta y explícitamente fuera del alcance de verificación automática de este change (ver proposal.md, "Out of scope"). Esto no bloquea `tasks`/`run` para escribir y verificar el código (Terraform + CI se verifican con `validate`/`fmt`/`plan` sin credenciales y build multi-arch en CI, per R1-R6) — sí bloquea cualquier verificación que dependa de una cuenta real, y el propio `apply` inicial (y, ahora, también el bootstrap manual del bucket de state del backend `oci` decidido en `design.md` D7).
- **Recomendación práctica** (del ADR 0001, ya documentada): al crear la tenancy, elegir **Frankfurt o Singapur** como home region (mitiga el riesgo de "out of host capacity" para instancias Ampere A1) — la home region no se puede cambiar después sin recrear la cuenta.
- **Resume command**: una vez creada la tenancy y generadas las credenciales de API (tenancy OCID, user OCID, fingerprint, private key): (1) crear el bucket de Object Storage para el state (bootstrap de D7, comandos en el README una vez escrito), (2) añadir los secrets al repo de GitHub, (3) disparar manualmente el workflow `infra-dev.yml` con `action: plan` como primera verificación real contra la cuenta.

<!-- Entrada 1 original (backend de state, R2) resuelta por el usuario 2026-07-20: backend nativo `oci`. Ver design.md D7. -->
