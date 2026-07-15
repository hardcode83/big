---
phases: [design, run]
---

# Security

## Data classification

<!-- What sensitive data exists (PII, PHI, credentials) and where it may live. -->

## Rules

<!-- Hard requirements, verifiable per change: -->
<!-- - All external input is validated at <layer>. -->
<!-- - Secrets only via <mechanism>; never in code, config files, or logs. -->
<!-- - AuthN/AuthZ: every new endpoint declares its required permission. -->

## Review triggers

<!-- Changes that require extra scrutiny before merging: new endpoints, -->
<!-- auth changes, new dependencies, data exports, infra exposure. -->
