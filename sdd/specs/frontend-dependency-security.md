# Seguridad de dependencias del frontend

## Purpose

Mantiene el árbol de dependencias del frontend reproducible y fuera de los rangos vulnerables conocidos. La aplicación se instala con Node 22 mediante el lockfile versionado, conserva las dependencias transitivas como transitivas y verifica por separado la exposición del árbol completo y del árbol desplegable.

## Requirements

### Resolución reproducible

- THE SYSTEM SHALL declare the frontend dependency contract in `frontend/package.json` and SHALL pin its reproducible resolution in `frontend/package-lock.json` (lockfile v3).
- WHEN the frontend is installed from a clean workspace with Node 22, THE SYSTEM SHALL complete `npm ci` without modifying the lockfile.
- THE SYSTEM SHALL keep `postcss`, `sharp` and `brace-expansion` as transitive dependencies; they SHALL NOT be added as direct application dependencies.

### Vulnerability remediation

- THE SYSTEM SHALL keep `next` at the first compatible corrected version selected for the current vulnerability baseline; the current resolution is 16.2.11.
- WHEN Next.js continues to resolve a vulnerable transitive package, THE SYSTEM SHALL use only a parent-scoped override for the first corrected compatible version; the current overrides are Next → PostCSS 8.5.18 and Next → Sharp 0.35.0.
- WHEN a parent naturally resolves a corrected transitive version, THE SYSTEM SHALL omit the corresponding override; the current `minimatch` branches naturally resolve `brace-expansion` 1.1.17 and 5.0.8.
- THE SYSTEM SHALL treat dependency overrides as temporary remediation and SHALL recheck their necessity when the corresponding parent dependency is upgraded.

### Verification and functional invariance

- WHEN the dependency tree is verified, THE SYSTEM SHALL run `npm audit` and `npm audit --omit=dev` and SHALL document any remaining advisory with its package, severity, route and exposure.
- WHEN the frontend is validated under Node 22, THE SYSTEM SHALL pass `npm test`, `npm run lint`, `npm run typecheck` and `npm run build`.
- THE SYSTEM SHALL preserve frontend behavior, dashboard components, mocks, API contracts and CI workflows while remediating dependencies.
- WHEN a dependency update changes observable SSR, routing, build or rendering behavior, THE SYSTEM SHALL identify the effect and demonstrate the absence of functional regressions before release.

## Key files

- `frontend/package.json` — direct dependency range and scoped temporary overrides.
- `frontend/package-lock.json` — reproducible resolved versions and integrity metadata.
- `frontend/devops/Dockerfile` — Node 22 standalone production image and build verification surface.
- `sdd/changes/archive/2026-08-02-frontend-dependency-security/design.md` — baseline evidence, decisions and verification record for the archived remediation.
