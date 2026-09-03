"""The `api/` layer of the `statements` module (design D9).

Same shape as `app/pricing/api/` and `app/maintenance/api/`. The four files this package
owns — `schemas`, `errors`, `dependencies`, `router` — split the FastAPI surface exactly
the same way the precedent modules do: `application/` never imports FastAPI; the routers
here translate the domain use cases into HTTP routes and the error mapper translates the
domain exceptions into the PRD §23 envelope (`tests/test_openapi_contract.py` is the guard).
"""