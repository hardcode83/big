from app.pricing.domain.constants import HORIZON_DAYS, OCCUPANCY_WINDOW_DAYS


def test_horizon_is_sixty_days() -> None:
    assert HORIZON_DAYS == 60


def test_occupancy_window_is_thirty_days() -> None:
    assert OCCUPANCY_WINDOW_DAYS == 30
