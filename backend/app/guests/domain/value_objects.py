"""Value objects of the guests domain (design D8).

`normalize_email` is intentionally a **second** definition of the same rule that
`app/auth/domain/value_objects.py` applies to users, and not an import of it. Two
reasons: the guest domain must not depend on the auth domain to compare two strings,
and the two rules answer different questions — for a user a normalised address is a
globally unique identity (ADR 0005, enforced by `uq_users_lower_email`), while for a
guest it is only a dedup hint, because `guests.email` is a plain index and the same
person can legitimately appear twice.

If the two ever need to *differ*, that is a bug in whichever change made them differ:
"the same email address" has one meaning in this system. Consolidating both into a
shared module is a candidate for the change that next touches `auth` (design D3 records
the same debt for the unit of work).
"""


def normalize_email(value: str) -> str:
    """`strip` + `lower`, applied in Python on both write and read.

    Never `lower()` inside the SQL: Postgres and Python do not agree on case folding
    for every alphabet, so folding on one side and storing raw on the other makes the
    lookup and the stored data disagree — the same trap documented at length in
    `app/auth/domain/value_objects.py`.
    """
    return value.strip().lower()
