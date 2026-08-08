# infra-dev-terraform

[INFRA] IaC real de `infra/environments/dev/` según ADR 0001 (Oracle Cloud, Ampere A1 Always Free): VCN/security list/instancia vía Terraform (`oracle/oci`), backend de state nativo `oci`, pipeline GitHub Actions (`plan`/`apply` manual + validación en PR) y build multi-arch (arm64) verificado en CI; despliegue de la app vía SSH queda fuera de alcance (workflow futuro); `terraform apply` real pendiente de confirmación explícita del usuario (no está en el PRD original, añadido tras `dev-hosting-provider`)
