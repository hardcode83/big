---
phases: [tasks, run]
---

# Testing

## Test types and when

<!-- What deserves unit / integration / E2E in this project, e.g.: -->
<!-- - Business logic: unit test next to the module. -->
<!-- - Anything crossing a boundary (DB, HTTP, queue): integration test. -->
<!-- - E2E only for the critical user flows listed below. -->
<!-- - Infra/dev-environment changes (docker-compose, Dockerfiles, CI config): -->
<!--   unit tests don't catch this. Verify by actually building the images and -->
<!--   running the real stack end-to-end (bring it up, hit the endpoints, check -->
<!--   logs) — that's what catches race conditions, bad depends_on/healthchecks, -->
<!--   wrong env wiring. Encode it as an explicit tasks.md Verification step, -->
<!--   not just "run the test suite". -->

## Conventions

<!-- Where tests live, naming, fixtures/factories location and how to reuse -->
<!-- them, what may be mocked and what must NEVER be mocked. -->

## Coverage & quality bars

<!-- Minimum coverage (and where it's enforced), flakiness policy, -->
<!-- what makes a test acceptable vs ceremonial. -->

## Commands

<!-- Only if beyond project.md: run one file, run by marker/tag, update -->
<!-- snapshots, run integration suite locally (docker-compose etc.). -->
