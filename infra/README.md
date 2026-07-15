# infra

Convención de despliegue remoto para AutoHostAI. Organizada **por entorno**, no por dominio de negocio — ver `sdd/steering/infra.md` para la convención completa, el criterio de decisión de proveedor cloud (pendiente) y la integración futura con CI/CD.

- `environments/dev/`, `environments/staging/`, `environments/prod/` — un root module de Terraform por entorno (sin proveedor elegido todavía, sin `.tf` real aún).
- `modules/` — módulos Terraform reutilizables entre entornos. No creado todavía; se añade cuando haya un primer módulo real que compartir.

Nada de esto sustituye al stack de desarrollo local (`docker-compose`/`Makefile` en la raíz del repo) — ver spec `sdd/specs/local-environment.md`.
