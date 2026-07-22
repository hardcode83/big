# BLOCKED — infra-dev-payg

## 5.2 · run · deferred — aplicar el resize vía pipeline tras el merge
Tareas 5.2 (R2/R3): la instancia sigue en 2 OCPU/12 GB/47 GB hasta que se ejecute el `apply` real. Debe hacerse por el pipeline (no local) tras mergear el PR: `workflow_dispatch` en `.github/workflows/infra-dev.yml` con `action=apply`, `ad_number=3`. Verificar en el run que el plan es `0 to destroy` antes de confirmar.
**Resume:** ejecutar el workflow_dispatch tras el merge; luego `/sdd:review infra-dev-payg` o `/sdd:archive infra-dev-payg`.

## 5.3 · run · deferred — expandir la partición en el SO tras el apply
Tarea 5.3 (R2): el boot volume crece a 200 GB en la nube pero el SO no lo usa hasta expandir la partición. Por SSH a la VM (`ubuntu@79.76.101.10`): `sudo /usr/libexec/oci-growfs -y` (o `sudo growpart /dev/sda 1 && sudo resize2fs /dev/sda1`), luego `df -h` para confirmar 200 GB usables.
**Resume:** tras 5.2, SSH a la VM y ejecutar oci-growfs; luego `/sdd:archive infra-dev-payg`.
