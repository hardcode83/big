"""reviews tenant config: top-N bound for the recurring-issues summary (R5.5)

Adds `tenant_configs.review_recurring_issues_top_n` with a `BETWEEN 1 AND 50` check
constraint. The default is `5`, matching the design (D11) and the entity default in
`app/tenants/domain/entities.py`. The check lives at the DDL because `int` would
silently accept `0` and negatives — a property whose summary reports zero issues is
not a property with no issues, it is a configuration bug, and the constraint is the
cheapest place to refuse it.

Revision ID: r3v1ew5a02
Revises: r3v1ew5a01
Create Date: 2026-09-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "r3v1ew5a02"
down_revision: Union[str, None] = "r3v1ew5a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_configs",
        sa.Column(
            "review_recurring_issues_top_n",
            sa.Integer(),
            server_default="5",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_tenant_configs_review_recurring_issues_top_n_positive",
        "tenant_configs",
        "review_recurring_issues_top_n BETWEEN 1 AND 50",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tenant_configs_review_recurring_issues_top_n_positive",
        "tenant_configs",
        type_="check",
    )
    op.drop_column("tenant_configs", "review_recurring_issues_top_n")
