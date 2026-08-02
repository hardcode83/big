"""Value objects of the tenant configuration (R5.5, R5.6, design D14).

Written before the implementation. `timezone` is the one that matters operationally:
`celery-jobs` will compute the check-in and checkout windows with it, so an invalid string
turns a configuration mistake into a scheduler failure.
"""

import pytest

from app.tenants.domain.exceptions import TenantValidationError
from app.tenants.domain.value_objects import (
    normalise_country,
    normalise_language,
    normalise_timezone,
)


@pytest.mark.parametrize(
    "value", ["Europe/Madrid", "UTC", "America/New_York", "Atlantic/Canary"]
)
def test_a_real_iana_zone_is_accepted(value: str) -> None:
    assert normalise_timezone(value) == value


@pytest.mark.parametrize(
    "value", ["Europe/Madridd", "Madrid", "GMT+1", "", "  ", "Europe/", "../etc/passwd"]
)
def test_an_invalid_zone_is_refused(value: str) -> None:
    with pytest.raises(TenantValidationError):
        normalise_timezone(value)


def test_the_zone_database_is_actually_available() -> None:
    """The functional half: zones resolve here and now.

    If this fails, EVERY zone is invalid — including the default — and this says so plainly
    rather than letting a hundred other tests fail obscurely.
    """
    from zoneinfo import available_timezones

    zones = available_timezones()
    assert "Europe/Madrid" in zones
    assert len(zones) > 100


def test_the_tzdata_distribution_is_installed() -> None:
    """The dependency half, and the reason it is a SEPARATE assertion (design D14).

    The QA panel of sections 7-8 showed that the test above cannot guard the dependency: the
    Debian base image ships an OS-level `tzdata` package under `/usr/share/zoneinfo`, and
    `zoneinfo` searches `TZPATH` **before** falling back to the PyPI package's bundled data. It
    proved it by blocking the `tzdata` import with a `sys.meta_path` finder — `Europe/Madrid`
    still resolved. So a `uv lock` that silently dropped `tzdata` would have kept that test
    green for ever, and the guard would only have failed the day the upstream image stopped
    shipping the OS package: a different trigger from the one the docstring claimed.

    Asking the package metadata is what actually detects the dependency going away. Both halves
    matter: the OS package is what makes it work today, and the declared one is what keeps it
    working on an image that does not carry it.
    """
    from importlib.metadata import distribution

    # Raises PackageNotFoundError if it is not installed, which is the failure to catch.
    assert distribution("tzdata").version


def test_the_zone_is_trimmed_but_not_case_folded() -> None:
    """IANA names are case-sensitive: `europe/madrid` is not a zone."""
    assert normalise_timezone("  Europe/Madrid  ") == "Europe/Madrid"

    with pytest.raises(TenantValidationError):
        normalise_timezone("europe/madrid")


@pytest.mark.parametrize("value,expected", [("es", "ES"), ("ES", "ES"), (" fr ", "FR")])
def test_a_two_letter_country_is_normalised_to_upper_case(value: str, expected: str) -> None:
    assert normalise_country(value) == expected


@pytest.mark.parametrize("value", ["E", "ESP", "1S", "e5", "", "  ", "ñs", "E S"])
def test_a_country_that_is_not_two_ascii_letters_is_refused(value: str) -> None:
    with pytest.raises(TenantValidationError):
        normalise_country(value)


def test_the_country_check_is_shape_only_and_says_so() -> None:
    """Documented limitation of design D14: `ZZ` is not a country but passes.

    Validating against the real ISO-3166-1 list needs a dependency (`pycountry`), and a new
    dependency is a review trigger in `steering/security.md`. This test exists so the
    limitation is recorded as a decision rather than discovered as a surprise.
    """
    assert normalise_country("ZZ") == "ZZ"


@pytest.mark.parametrize("value,expected", [("es", "es"), ("EN", "en"), (" es ", "es")])
def test_a_supported_language_is_normalised_to_lower_case(value: str, expected: str) -> None:
    assert normalise_language(value) == expected


@pytest.mark.parametrize("value", ["fr", "de", "esp", "", "e"])
def test_an_unsupported_language_is_refused(value: str) -> None:
    """`es` and `en` are the two locales that exist in `frontend/locales/`."""
    with pytest.raises(TenantValidationError):
        normalise_language(value)
