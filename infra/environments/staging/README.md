# Entorno: staging

**Propósito:** réplica de `prod` para validar releases antes de desplegar a producción — mismo proveedor/configuración que `prod`, a menor escala.

**Estado:** sin proveedor cloud elegido; sin Terraform real todavía. Aquí irán los `.tf` de este entorno (`main.tf`, `variables.tf`, `backend.tf`) una vez decidido.

Ver `sdd/steering/infra.md` para la convención completa y el criterio de decisión de proveedor.
