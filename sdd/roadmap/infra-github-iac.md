# infra-github-iac

[INFRA] gestionar la parte GitHub-side como código con el provider `integrations/github` (Actions secrets/variables, instalación de la App, acceso a packages, ajustes de repo), eliminando los pasos a mano en GitHub que tuvo `app-deploy-dev`; el bootstrap irreducible (org, GitHub App, clave privada) queda documentado. Cumple la norma IaC-first de `steering/infra.md` (no está en el plan original, añadido tras `app-deploy-dev`)
