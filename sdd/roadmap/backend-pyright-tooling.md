# backend-pyright-tooling

declarar Pyright y su runtime Node (`nodejs-wheel`, fijado por hash en `uv.lock`) como deps de desarrollo y `libatomic1` sólo en la imagen `dev`, de modo que `uv run pyright .` arranque sin `uvx` ni descarga por `nodeenv`. No añade gate de CI (decisión aparte). No está en el plan original, añadido para desbloquear el tooling estático que `revenue-statements` §11.2 necesitaba.
