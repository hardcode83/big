from datetime import date

import pytest

from app.pricing.domain.holidays import (
    COVERED_YEARS,
    ES_NATIONAL,
    SPAIN_NATIONAL_HOLIDAY_NAMES,
    SPAIN_NATIONAL_HOLIDAYS,
    SUPPORTED_HOLIDAY_CATALOGS,
    holiday_name,
)

FIXED_DAYS = ((1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25))

# Easter Sunday 2025-04-20, 2026-04-05, 2027-03-28.
GOOD_FRIDAYS = (date(2025, 4, 18), date(2026, 4, 3), date(2027, 3, 26))


def test_the_catalogue_covers_2025_to_2027() -> None:
    assert COVERED_YEARS == (2025, 2026, 2027)
    assert {day.year for day in SPAIN_NATIONAL_HOLIDAYS} == set(COVERED_YEARS)


@pytest.mark.parametrize("year", COVERED_YEARS)
def test_each_year_has_the_nine_fixed_days_plus_good_friday(year: int) -> None:
    days_of_year = {day for day in SPAIN_NATIONAL_HOLIDAYS if day.year == year}

    assert len(days_of_year) == len(FIXED_DAYS) + 1


@pytest.mark.parametrize("year", COVERED_YEARS)
@pytest.mark.parametrize(("month", "day"), FIXED_DAYS)
def test_the_fixed_days_are_present(year: int, month: int, day: int) -> None:
    assert date(year, month, day) in SPAIN_NATIONAL_HOLIDAYS


@pytest.mark.parametrize("good_friday", GOOD_FRIDAYS)
def test_the_movable_day_of_each_year_is_present(good_friday: date) -> None:
    assert good_friday in SPAIN_NATIONAL_HOLIDAYS
    assert holiday_name(good_friday) == "Good Friday"


def test_an_ordinary_day_has_no_name() -> None:
    assert holiday_name(date(2026, 8, 16)) is None
    assert date(2026, 8, 16) not in SPAIN_NATIONAL_HOLIDAYS


def test_every_holiday_has_a_name() -> None:
    assert set(SPAIN_NATIONAL_HOLIDAY_NAMES) == set(SPAIN_NATIONAL_HOLIDAYS)
    assert all(name for name in SPAIN_NATIONAL_HOLIDAY_NAMES.values())


def test_the_catalogue_is_immutable() -> None:
    assert isinstance(SPAIN_NATIONAL_HOLIDAYS, frozenset)
    with pytest.raises(TypeError):
        SPAIN_NATIONAL_HOLIDAY_NAMES[date(2026, 2, 2)] = "invented"  # type: ignore[index]


def test_es_national_is_the_only_admitted_catalogue() -> None:
    assert SUPPORTED_HOLIDAY_CATALOGS == frozenset({ES_NATIONAL})
    assert ES_NATIONAL == "ES_NATIONAL"
