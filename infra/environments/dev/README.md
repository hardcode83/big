# Entorno: dev

**Propósito:** entorno remoto de desarrollo/integración — el primero en recibir despliegues automáticos, para probar cambios de infra o de aplicación fuera del stack local antes de `staging`/`prod`.

**Estado:** proveedor decidido — Oracle Cloud Infrastructure, VM única (Ampere A1, Always Free) + docker-compose. Ver `docs/adr/0001-dev-hosting-provider.md` para la justificación completa. Sin Terraform real todavía — el `.tf` de este entorno (`main.tf`, `variables.tf`, `backend.tf`) se escribe en un change posterior, que debe verificar/añadir build multi-arch ARM64 en CI antes del primer `apply` (ver Consecuencias del ADR).

Ver `sdd/steering/infra.md` para la convención completa y la tabla comparativa histórica de proveedores.
