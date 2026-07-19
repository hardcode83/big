# infra

Convención de despliegue remoto para AutoHostAI. Organizada **por entorno**, no por dominio de negocio — ver `sdd/steering/infra.md` para la convención completa, el estado de la decisión de proveedor cloud por entorno, y la integración futura con CI/CD.

- `environments/dev/` — proveedor decidido (Oracle Cloud, ver `docs/adr/0001-dev-hosting-provider.md`), sin `.tf` real todavía. `environments/staging/`, `environments/prod/` — sin proveedor elegido, sin `.tf` real. Un root module de Terraform independiente por entorno.
- `modules/` — módulos Terraform reutilizables entre entornos. No creado todavía; se añade cuando haya un primer módulo real que compartir.

Nada de esto sustituye al stack de desarrollo local (`docker-compose`/`Makefile` en la raíz del repo) — ver spec `sdd/specs/local-environment.md`.
