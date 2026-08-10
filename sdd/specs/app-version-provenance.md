# Procedencia de la versión desplegada

## Purpose

Permite a un operador autenticado relacionar la identidad pública del build con el Pull Request,
commit y ejecución de GitHub Actions que produjeron el despliegue, sin publicar la procedencia
privada en superficies anónimas ni consultar GitHub en runtime.

## Requirements

### Contrato y endpoint backend

- THE SYSTEM SHALL expose `GET /api/v1/provenance` behind `Permission.READ_BUILD_PROVENANCE`,
  with `Cache-Control: private, no-store` and an explicit OpenAPI response contract.
- THE SYSTEM SHALL grant `READ_BUILD_PROVENANCE` only to `TENANT_OWNER` and `PROPERTY_MANAGER`;
  anonymous callers, `CLEANER` and `TECHNICIAN` SHALL be denied.
- THE SYSTEM SHALL return `app_version` independently of private provenance availability.
- WHEN repository URL, Pull Request number, full commit SHA and Actions run ID are all present
  and valid, THE SYSTEM SHALL return them as one complete provenance block.
- IF any private provenance field is absent, malformed, or fails the canonical contract,
  THEN THE SYSTEM SHALL return `provenance: null`/`unavailable` without partial private values
  or a server error.
- THE SYSTEM SHALL validate repository URLs as HTTPS GitHub URLs, Pull Request and run IDs as
  positive numbers, and the commit as exactly 40 hexadecimal characters.

### Producer and transport

- THE SYSTEM SHALL derive provenance in the CD `provenance` job from the repository context,
  commit subject, commit SHA and Actions run ID; it SHALL validate the repository URL before
  publishing outputs.
- THE SYSTEM SHALL write `APP_VERSION` and the four `APP_PROVENANCE_*` values only to the
  private deployment environment and inject them only into `backend`; frontend, worker, beat,
  migrate and cloudflared SHALL NOT receive them.
- THE SYSTEM SHALL extract Pull Request numbers only from supported merge subjects (`Merge pull
  request #N ...` and a title suffix `(#N)`), returning unknown for issue numbers and ambiguous
  formats.
- THE SYSTEM SHALL NOT query GitHub at runtime and SHALL NOT require GitHub secrets or tokens
  to serve provenance.

### Authenticated frontend panel

- WHEN an authenticated workspace operator opens the provenance panel, THE SYSTEM SHALL request
  the protected endpoint using the in-memory bearer and show the shared version plus links to
  the Pull Request, commit and Actions run when the complete block is available.
- THE SYSTEM SHALL fetch provenance only when the panel is opened, retain it in memory, and show
  localized loading, error and unknown states without fabricating partial links.
- THE SYSTEM SHALL keep the panel within authenticated workspace shells and SHALL NOT render it
  in `RootLayout`, `PublicShell`, `GuestShell`, field shells, `/login` or `/guest/[token]`.
- THE SYSTEM SHALL keep the private repository URL, Pull Request number, full SHA and run ID out
  of `NEXT_PUBLIC_*`, `PublicRuntimeConfig`, root layout props, anonymous HTML, static assets and
  public JavaScript bundles.

### Version parity and congruence

- THE SYSTEM SHALL provide `make check-version-parity` at the repository root to compare
  `VERSION` with the `version` fields in `backend/pyproject.toml` and `frontend/package.json`;
  missing, empty or divergent values SHALL produce a non-zero exit code naming each problem.
- THE SYSTEM SHALL run the extractor self-test, version-parity gate and producer/consumer
  provenance congruence checks in CI, rejecting private fields in the public frontend contract.

## Key files

- `backend/app/provenance/` — backend contract, validation, authorization and endpoint.
- `.github/scripts/extract-pr.sh` — supported Pull Request subject extractor and self-test.
- `.github/workflows/deploy-dev.yml` and `docker-compose.deploy.yml` — CD production and private transport.
- `frontend/features/provenance/` — authenticated panel and in-memory client state.
- `scripts/check-version-parity.py` and `Makefile` — host-side version parity gate.
- `docs/app-version-provenance.md` — operational interpretation and rollback procedure.
