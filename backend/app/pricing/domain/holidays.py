"""Spain's national holidays 2025-2027, embedded (PRD §19, design D7).

The PRD asks for a hardcoded list and not a library: "MVP: lista de festivos nacionales
España hardcodeada para años 2025-2027". Municipal holidays stay manual `event_rules`, as
the PRD itself declares.

Two things this list deliberately is not:

- It is **not** the BOE labour calendar. That one substitutes a holiday falling on a Sunday
  per autonomous community, which is a per-region decision this catalogue has no way to
  make. What is listed here is the national set: **nine fixed dates** — Epiphany among them,
  on 6 January — plus Good Friday, ten per year.
- It is **not** a computus. Good Friday is written out year by year, which is what makes
  the catalogue a constant that a test can pin instead of an algorithm that can drift.

`ES_NATIONAL` is the only catalogue identifier a rule may reference; an open namespace
would invite keys nobody resolves.

`ASSUMPTION` (R2.6): the PRD fixes the list of holidays but **not** what modifier each one
deserves, so this catalogue supplies only the dates and the percentage comes from the
`event_rule` that references it — `{"holidays": "ES_NATIONAL", "modifier_pct": 15}`.
Municipal holidays stay manual `event_rules`, as PRD §19 declares.
"""

from datetime import date
from types import MappingProxyType
from typing import Mapping

#: The only catalogue identifier `event_rules` accepts (design D7).
ES_NATIONAL = "ES_NATIONAL"

SUPPORTED_HOLIDAY_CATALOGS: frozenset[str] = frozenset({ES_NATIONAL})

_NEW_YEAR = "New Year's Day"
_EPIPHANY = "Epiphany"
_GOOD_FRIDAY = "Good Friday"
_LABOUR_DAY = "Labour Day"
_ASSUMPTION = "Assumption of Mary"
_NATIONAL_DAY = "National Day of Spain"
_ALL_SAINTS = "All Saints' Day"
_CONSTITUTION = "Constitution Day"
_IMMACULATE = "Immaculate Conception"
_CHRISTMAS = "Christmas Day"

#: Good Friday moves with Easter; written out rather than computed (see module docstring).
_GOOD_FRIDAYS = (date(2025, 4, 18), date(2026, 4, 3), date(2027, 3, 26))

_FIXED_DAYS: tuple[tuple[int, int, str], ...] = (
    (1, 1, _NEW_YEAR),
    (1, 6, _EPIPHANY),
    (5, 1, _LABOUR_DAY),
    (8, 15, _ASSUMPTION),
    (10, 12, _NATIONAL_DAY),
    (11, 1, _ALL_SAINTS),
    (12, 6, _CONSTITUTION),
    (12, 8, _IMMACULATE),
    (12, 25, _CHRISTMAS),
)

COVERED_YEARS: tuple[int, ...] = (2025, 2026, 2027)


def _build() -> Mapping[date, str]:
    days: dict[date, str] = {}
    for year in COVERED_YEARS:
        for month, day, name in _FIXED_DAYS:
            days[date(year, month, day)] = name
    for good_friday in _GOOD_FRIDAYS:
        days[good_friday] = _GOOD_FRIDAY
    return MappingProxyType(dict(sorted(days.items())))


#: Every national holiday in the covered years, with the name the explanation renders.
SPAIN_NATIONAL_HOLIDAY_NAMES: Mapping[date, str] = _build()

#: The same catalogue as a membership test (design D7).
SPAIN_NATIONAL_HOLIDAYS: frozenset[date] = frozenset(SPAIN_NATIONAL_HOLIDAY_NAMES)


def holiday_name(day: date) -> str | None:
    """Name of the national holiday on `day`, or `None` if it is an ordinary day."""
    return SPAIN_NATIONAL_HOLIDAY_NAMES.get(day)
