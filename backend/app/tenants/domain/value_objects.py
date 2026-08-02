"""Validated scalars of the tenant configuration (R5.5, R5.6, design D14).

Pure domain: `zoneinfo` and `re` are standard library, so the purity `tests/test_layering.py`
enforces holds.
"""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.tenants.domain.exceptions import TenantValidationError

# The two locales that exist in `frontend/locales/`. A third one is a frontend change first.
SUPPORTED_LANGUAGES = ("es", "en")

# `ASSUMPTION`: ISO-3166-1 alpha-2 by SHAPE only. A stated limitation of design D14, not an
# oversight: checking against the real list needs `pycountry`, and a new dependency is a review
# trigger in `steering/security.md`. `ZZ` passes. What this does catch is the mistake that
# happens — a three-letter code, a country name, a stray digit.
_COUNTRY = re.compile(r"^[A-Za-z]{2}$")


def normalise_timezone(value: str) -> str:
    """The IANA zone name, or `TenantValidationError`.

    Validated by constructing the zone, because that is the same thing `celery-jobs` will do
    every minute: anything `ZoneInfo` refuses here would refuse there, except there it would be
    a scheduler crash instead of a `422`.

    Trimmed but NOT case-folded — IANA names are case-sensitive, so `europe/madrid` is not a
    zone and pretending otherwise would accept a value that fails later.
    """
    candidate = value.strip()
    if not candidate:
        raise TenantValidationError("timezone cannot be empty")
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as error:
        # ValueError covers the traversal-looking inputs ZoneInfo rejects outright
        # (`../etc/passwd`), KeyError some malformed keys. All three mean the same thing here.
        raise TenantValidationError(f"{candidate!r} is not a known IANA time zone") from error
    return candidate


def normalise_country(value: str) -> str:
    """Two ASCII letters, upper-cased. Shape only — see the module comment."""
    candidate = value.strip()
    if not _COUNTRY.match(candidate):
        raise TenantValidationError(
            f"{candidate!r} is not a two-letter country code (ISO-3166-1 alpha-2)"
        )
    return candidate.upper()


def normalise_language(value: str) -> str:
    """One of the supported locales, lower-cased."""
    candidate = value.strip().lower()
    if candidate not in SUPPORTED_LANGUAGES:
        raise TenantValidationError(
            f"{candidate!r} is not a supported language; expected one of "
            f"{', '.join(SUPPORTED_LANGUAGES)}"
        )
    return candidate
