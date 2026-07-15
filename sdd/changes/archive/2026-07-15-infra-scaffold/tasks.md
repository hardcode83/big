# Tasks: infra-scaffold

## 1. Steering: `sdd/steering/infra.md`

- [x] 1.1 Crear `sdd/steering/infra.md` con frontmatter `applies_to: ["infra/**"]`, sin `phases` (D2) — files: `sdd/steering/infra.md` [R2]
- [x] 1.2 Sección de convención de layout: `infra/environments/<entorno>/` + mención de futuro `infra/modules/` (root modules por entorno + módulos Terraform reutilizables, no creado aún) (D1) — files: `sdd/steering/infra.md` [R1]
- [x] 1.3 Tabla comparativa de proveedor: AWS / Google Cloud / Vercel / Railway × 6 criterios (coste a escala 2 viviendas, Postgres/Redis gestionado, migración desde imágenes Docker de `local-environment`, integración CI/CD, vendor lock-in, madurez del provider de Terraform) — sin veredicto, estado explícito "pendiente de decisión" (D3) — files: `sdd/steering/infra.md` [R2]
- [x] 1.4 Sección "Integración futura con CI/CD": GitHub Actions (`.github/workflows/`, no creado) ejecutando `terraform plan`/`apply` contra `infra/environments/<entorno>/`; nota de que cualquier `.tf`/workflow real requiere su propio `/sdd-new` (D5) — files: `sdd/steering/infra.md` [R4]

## 2. Referencias cruzadas

- [x] 2.1 Añadir en `sdd/steering/architecture.md` una línea (sección "Forma del sistema"/"Monorepo") apuntando a `sdd/steering/infra.md` (D6) — files: `sdd/steering/architecture.md` [R2]
- [x] 2.2 Actualizar `sdd/project.md` — línea de Conventions "Reglas duras en `steering/`: ..." para incluir `infra.md` en la lista — files: `sdd/project.md` [R2]

## 3. Scaffold de `/infra`

- [x] 3.1 `infra/README.md`: índice raíz explicando la convención (por entorno, no por dominio de negocio) y enlazando a `sdd/steering/infra.md` — files: `infra/README.md` [R1, R2]
- [x] 3.2 `infra/environments/dev/README.md`, `infra/environments/staging/README.md`, `infra/environments/prod/README.md` con la plantilla fija (D4): propósito del entorno, estado ("sin proveedor elegido; aquí irán `main.tf`/`variables.tf`/`backend.tf`"), enlace a `sdd/steering/infra.md` — files: 3× `README.md` [R1, R3]

## 4. Verification

- [x] 4.1 Revisión manual: ningún directorio bajo `infra/` está organizado por dominio de negocio (`auth`, `cleaning`, `reservations`, ...) [R1]
- [x] 4.2 `grep` confirma que no existe ningún `.tf` ni `.github/workflows/*.yml` en el repo tras este change (R3.2, R4.2) — comando: `find infra .github -name '*.tf' -o -path '*workflows*'` sin resultados [R3, R4]
- [x] 4.3 Confirmar que `sdd/steering/infra.md` tiene el frontmatter correcto (`applies_to`, sin `phases`) y que las referencias cruzadas (`architecture.md`, `project.md`) enlazan correctamente [R2]
