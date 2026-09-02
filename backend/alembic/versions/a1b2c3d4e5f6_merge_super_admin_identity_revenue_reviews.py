"""merge heads: super-admin-identity and revenue-reviews

Two parallel changes branched from `e5c9b1f47a28` (the `notifications_read_at`
migration) and shipped separately:

- `c22b8ae01096` — `super-admin-identity` relaxed `NOT NULL` on `users.tenant_id`
  and `user_sessions.tenant_id` so `SUPER_ADMIN` rows could carry no tenant.
- `r3v1ew5a01` → `r3v1ew5a03` — `revenue-reviews` created the `reviews`
  and `review_response_drafts` tables, added `TenantConfig.review_recurring_issues_top_n`,
  and broadened `TimelineEventType` with five review events.

Neither migration touches the other's tables — both are pure DDL of disjoint
schema objects. After the merge of `sdd/revenue-reviews` into `main` (PR #151)
the lineage has two leaves: `c22b8ae01096` and `r3v1ew5a03`. Alembic refuses
to upgrade with multiple heads (`Multiple head revisions are present for given
argument 'head'`), and `backend-tests-suite` reports `migration failure` until
the graph is single-rooted.

This revision is the merge point: `down_revision` lists both leaves as a
sequence, the body is empty (`upgrade` and `downgrade` are no-ops because
the leaves themselves already applied everything), and a future
`alembic heads` reports exactly this revision. Nothing here moves data; the
graph change is the whole content.

If a future change branches from before this merge (rare but possible during
a long-lived feature branch), its `down_revision` should name this revision,
not the leaves it consolidates — otherwise the multi-head returns.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = ("c22b8ae01096", "r3v1ew5a03")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: this migration exists to unify two leaves of the Alembic graph."""
    pass


def downgrade() -> None:
    """No-op: dropping this revision returns the graph to two heads.

    Downgrade is intentionally empty rather than refusing — the leaves on
    either side already carry their full `downgrade()` payload, so a reviewer
    can drop this revision independently without losing the ability to walk
    each branch back to its origin.
    """
    pass
