"""One Redis logical database per xdist worker (R3.4, design D6).

Postgres gets a throwaway database per worker from `tests/db_names.py`. Redis has no
equivalent, and the suite uses production key names deliberately —
`tests/scheduler/test_dispatch_task.py` takes the real `dispatch_notifications` lock and
another test demands to find it free — so two workers on one Redis would cross.
"""

import pytest

from tests.conftest import _REDIS_LOGICAL_DATABASES, _redis_url_for_this_worker

URL = "redis://redis:6379/0"


def test_without_xdist_the_url_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """The serial run is the default and must not change at all."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    assert _redis_url_for_this_worker(URL) == URL


def test_two_workers_resolve_different_logical_databases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    first = _redis_url_for_this_worker(URL)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    second = _redis_url_for_this_worker(URL)

    assert (first, second) == ("redis://redis:6379/0", "redis://redis:6379/3")
    assert first != second


def test_a_worker_past_the_last_logical_database_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard D6 asks for. Wrapping around would put the collision back in silence."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", f"gw{_REDIS_LOGICAL_DATABASES}")

    with pytest.raises(RuntimeError, match="needs Redis logical database"):
        _redis_url_for_this_worker(URL)


def test_the_last_usable_worker_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The boundary itself, so the guard cannot drift by one without a test saying so."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", f"gw{_REDIS_LOGICAL_DATABASES - 1}")

    assert _redis_url_for_this_worker(URL).endswith(f"/{_REDIS_LOGICAL_DATABASES - 1}")


def test_an_unrecognised_worker_id_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")

    with pytest.raises(RuntimeError, match="unexpected pytest-xdist worker id"):
        _redis_url_for_this_worker(URL)
