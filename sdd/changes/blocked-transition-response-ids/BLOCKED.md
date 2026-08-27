# Blocked entries

Each entry: **phase** · **type** (`decision` = needs a human, `deferred` = the flow can resume it) · **what & why** · **exact resume command**.

## Entry 1 — DELETED — R3.3 / R4.4 contract mismatch

Resolved by fix commit `ac78d1b`. `BlockedTransitionListQuery` now carries `extra="forbid"`
(`schemas.py:410-426`), the route binds it as `Annotated[…, Query()]` (`router.py:279`), and
`test_tenant_id_in_query_string_is_rejected_with_422` asserts both the 422 status and the
envelope’s named field (`test_action_id_isolation.py:316-363`). Three re-reviewers
(architect, security, tenancy) and QA all PASS.

## Entry 2 — DELETED — R4.3 test mis-scoped

Resolved by fix commit `ac78d1b`. Test renamed to
`test_a_cleaning_stall_with_no_live_task_lists_with_null_id_even_if_neighbour_has_one`
(`test_action_id_isolation.py:261-309`); docstring documents the structural invariant
(`cleaning_tasks.property_id` always points to a property in the same tenant); `body["total"]
== 1` added as a sharper assertion.

## Entry 3 — Test double hygiene: FakeIncidentReader ignores tenant_id (tenancy F3, deferred)

- **phase**: review
- **type**: deferred
- **what & why**: `backend/tests/dashboard/doubles.py:181-197` accepts `tenant_id` but does not filter by it; the loop iterates `open_by_property` by property_id only. The unit tests under `test_action_id_resolver.py` only seed one tenant, so the missing filter is benign today. A future multi-tenant unit test would silently mix data. This is a hygiene gap, not a security defect (the integration suite uses the real DB via the HTTP endpoint). The home for this is `tasks.md §8`.
- **resume command**: not blocking ship. Open a follow-up change when a multi-tenant unit test is needed. For now, accept the deferred state.

## Entry 4 — Schema test gap: invalid UUID rejected by Pydantic but not tested (qa F3, deferred)

- **phase**: review
- **type**: deferred
- **what & why**: `BlockedTransitionResponse(cleaning_task_id="not-a-uuid")` is correctly rejected by Pydantic v2 (verified by direct probe), but no test asserts this. The proposal's R1.1 specifies `uuid.UUID | None` so the type IS enforced; the coverage is silent on the bad-input case. Low severity — production behaviour is correct. The home for this is `tasks.md §8`.
- **resume command**: not blocking ship. If desired, add a parameterised test alongside the existing `test_each_of_the_six_original_fields_is_required` test in `backend/tests/properties/test_blocked_transition_response.py`. A follow-up change can cover it.

## Entry 5 — `sdd/roadmap.md` line pending archive (not in implementation commit)

- **phase**: review (working-tree hygiene)
- **type**: deferred
- **what & why**: The implementation commit (`0b8b7a5`) correctly excludes `sdd/roadmap.md` per shared rule 1 (only `/sdd:archive` writes roadmap post-merge). The working tree still has the change's roadmap entry as `M sdd/roadmap.md` — added during /sdd:run's section 5 work. This is expected; the entry will land when `/sdd:archive` runs after merge. The fix commit (`ac78d1b`) likewise does not touch `sdd/roadmap.md`. No action needed in /sdd:run or /sdd:review; flagged here so the dirty-state is not mistaken for uncommitted work.
- **resume command**: nothing. The dirty line will be absorbed by `/sdd:archive` post-merge.

---

**Ship-gate note.** The memory `blocked-md-must-be-empty-to-ship.md` records that the archive
ship gate rejects any non-empty BLOCKED.md. Entries 3, 4, 5 are not blockers per their
deferred type and have homes elsewhere (`tasks.md §8` for 3 and 4; the post-merge archive
for 5), but if a future ship-gate check is stricter than rule 5's allowance for deferred
items, those entries should be deleted at that point. The fix-loop entries (1, 2) are gone.
