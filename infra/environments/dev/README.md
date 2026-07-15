# Entorno: dev

**Propósito:** entorno remoto de desarrollo/integración — el primero en recibir despliegues automáticos, para probar cambios de infra o de aplicación fuera del stack local antes de `staging`/`prod`.

**Estado:** sin proveedor cloud elegido; sin Terraform real todavía. Aquí irán los `.tf` de este entorno (`main.tf`, `variables.tf`, `backend.tf`) una vez decidido.

Ver `sdd/steering/infra.md` para la convención completa y el criterio de decisión de proveedor.
