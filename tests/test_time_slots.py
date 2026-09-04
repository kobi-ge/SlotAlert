from datetime import datetime, timezone
import pytest
from src.utils.time import (
    TIME_SLOT_HEBREW_LABELS,
    calculate_day_of_week,
    determine_time_slot,
    get_time_slot,
)


def test_time_slot_resolution_exact_16_00():
    """
    Specifically assert that exactly 16:00 resolves to EVENING and never None.
    This was the primary root cause of the regression.
    """
    dt_16_00 = datetime(2026, 9, 3, 16, 0)
    slot = get_time_slot(dt_16_00)
    assert slot == "EVENING"
    assert determine_time_slot(dt_16_00) == "EVENING"
    assert slot is not None


def test_all_boundary_hours():
    """
    Test every critical boundary hour and minute to ensure continuous coverage:
    - 07:59 (MORNING)
    - 08:00 (MORNING)
    - 11:59 (MORNING)
    - 12:00 (AFTERNOON)
    - 15:59 (AFTERNOON)
    - 16:00 (EVENING)
    - 16:01 (EVENING)
    - 21:59 (EVENING)
    - 22:00 (EVENING)
    - 22:59 (EVENING)
    """
    cases = [
        # Morning boundaries
        (datetime(2026, 9, 4, 6, 0), "MORNING"),
        (datetime(2026, 9, 4, 7, 59), "MORNING"),
        (datetime(2026, 9, 4, 8, 0), "MORNING"),
        (datetime(2026, 9, 4, 11, 59), "MORNING"),
        # Afternoon boundaries
        (datetime(2026, 9, 4, 12, 0), "AFTERNOON"),
        (datetime(2026, 9, 4, 15, 59), "AFTERNOON"),
        # Evening boundaries (including exact 16:00 gap fix)
        (datetime(2026, 9, 4, 16, 0), "EVENING"),
        (datetime(2026, 9, 4, 16, 1), "EVENING"),
        (datetime(2026, 9, 4, 21, 59), "EVENING"),
        (datetime(2026, 9, 4, 22, 0), "EVENING"),
        (datetime(2026, 9, 4, 22, 59), "EVENING"),
    ]

    for dt, expected_slot in cases:
        actual = get_time_slot(dt)
        assert actual == expected_slot, f"Failed at {dt.strftime('%H:%M')}: expected {expected_slot}, got {actual}"
        assert actual is not None


def test_off_peak_night_fallback():
    """
    Ensure off-peak and night hours never return None and resolve sensibly.
    """
    night_cases = [
        (datetime(2026, 9, 4, 23, 0), "EVENING"),
        (datetime(2026, 9, 4, 23, 59), "EVENING"),
        (datetime(2026, 9, 4, 0, 0), "MORNING"),
        (datetime(2026, 9, 4, 2, 30), "MORNING"),
        (datetime(2026, 9, 4, 5, 59), "MORNING"),
    ]

    for dt, expected_slot in night_cases:
        actual = get_time_slot(dt)
        assert actual is not None
        assert actual == expected_slot, f"Off-peak {dt.strftime('%H:%M')} expected {expected_slot}, got {actual}"


def test_24_hours_continuous_coverage():
    """Verify that every single hour from 0 to 23 returns a valid, non-empty time slot."""
    valid_slots = {"MORNING", "AFTERNOON", "EVENING"}
    for h in range(24):
        dt = datetime(2026, 9, 4, h, 30)
        slot = get_time_slot(dt)
        assert slot in valid_slots, f"Hour {h}:30 returned invalid slot '{slot}'"
        assert slot in TIME_SLOT_HEBREW_LABELS, f"Missing Hebrew label for slot '{slot}'"


def test_calculate_day_of_week():
    """Verify Israeli week day calculation (0=Sunday ... 6=Saturday)."""
    # 2026-09-06 is Sunday -> 0
    assert calculate_day_of_week(datetime(2026, 9, 6)) == 0
    # 2026-09-07 is Monday -> 1
    assert calculate_day_of_week(datetime(2026, 9, 7)) == 1
    # 2026-09-11 is Friday -> 5
    assert calculate_day_of_week(datetime(2026, 9, 11)) == 5
    # 2026-09-12 is Saturday -> 6
    assert calculate_day_of_week(datetime(2026, 9, 12)) == 6
