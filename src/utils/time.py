"""
Time and date calculation utilities for slot categorization and candidate matching.
Guarantees continuous 24/7 boundary coverage with zero unmapped dead zones.
"""
from datetime import datetime
from typing import Dict

# Hebrew Day Names (0=Sunday ... 6=Saturday)
HEBREW_DAYS: Dict[int, str] = {
    0: "ראשון",
    1: "שני",
    2: "שלישי",
    3: "רביעי",
    4: "חמישי",
    5: "שישי",
    6: "שבת",
}

# Standard Hebrew Labels for Time Slots
TIME_SLOT_HEBREW_LABELS: Dict[str, str] = {
    "MORNING": "בוקר (08:00-12:00)",
    "AFTERNOON": "צהריים (12:00-16:00)",
    "EVENING": "ערב (16:00-22:00)",
}

# Backward compatibility alias
TIME_SLOT_LABELS = TIME_SLOT_HEBREW_LABELS


def calculate_day_of_week(dt: datetime) -> int:
    """
    Convert datetime to day of week where:
    0 = Sunday, 1 = Monday, ..., 5 = Friday, 6 = Saturday.
    (Python dt.weekday() returns 0=Monday ... 6=Sunday).
    """
    return (dt.weekday() + 1) % 7


def get_time_slot(dt: datetime) -> str:
    """
    Determine time_slot category based on slot start hour with continuous 24/7 coverage.
    
    Mutually exclusive, continuous boundary definitions:
    - MORNING:   06:00 <= hour < 12:00 (06:00 - 11:59)
    - AFTERNOON: 12:00 <= hour < 16:00 (12:00 - 15:59)
    - EVENING:   16:00 <= hour < 23:00 (16:00 - 22:59, strictly including 16:00)
    
    Off-peak / Night fallback:
    - 23:00 - 23:59 -> 'EVENING'
    - 00:00 - 05:59 -> 'MORNING'
    
    Under no circumstances does this function return None.
    """
    hour = dt.hour
    if 6 <= hour < 12:
        return "MORNING"
    elif 12 <= hour < 16:
        return "AFTERNOON"
    elif 16 <= hour < 23:
        return "EVENING"
    elif hour >= 23:
        # Off-peak late night fallback
        return "EVENING"
    else:
        # Off-peak early morning fallback (0 <= hour < 6)
        return "MORNING"


# Alias for backward compatibility
determine_time_slot = get_time_slot
