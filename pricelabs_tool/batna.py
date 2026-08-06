"""BATNA floor resolution and price adjustment with minimum-rate clamping."""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple


def get_listing_config_entry(
    listing_id: str, prop_config: Dict
) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Return (listing entry, property data) for a configured listing id."""
    lid = str(listing_id)
    for prop_data in prop_config.values():
        if not isinstance(prop_data, dict):
            continue
        for entry in prop_data.get("listings", []):
            if str(entry.get("id")) == lid:
                return entry, prop_data
    return None, None


BATNA_TIER_STEP = 0.15  # Thu/Sun +15% over Mon-Wed; Fri/Sat +15% over Thu/Sun


def is_weekend_day(weekday: int) -> bool:
    """True for Friday/Saturday (weekday: Mon=0 .. Sun=6). Sun-Thu use weekday BATNA."""
    return weekday in (4, 5)


def batna_tier_multiplier(weekday: int) -> float:
    """
    Three-tier BATNA from Mon-Wed base (weekday: Mon=0 .. Sun=6).
    Mon-Wed: 1.0 | Thu & Sun: 1.15 | Fri & Sat: 1.15^2
    """
    if weekday in (0, 1, 2):
        return 1.0
    if weekday in (3, 6):
        return 1.0 + BATNA_TIER_STEP
    if weekday in (4, 5):
        return (1.0 + BATNA_TIER_STEP) ** 2
    return 1.0


def three_tier_batna_floor(base_batna: float, weekday: int) -> float:
    """Compute day-of-week BATNA floor from Mon-Wed base rate."""
    base = float(base_batna)
    if weekday in (0, 1, 2):
        return round(base)
    if weekday in (3, 6):
        return round(base * 115 / 100)
    if weekday in (4, 5):
        return round(base * 13225 / 10000)
    return round(base)


def _parse_date(date_str: str) -> Optional[date]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def is_date_in_batna_exempt_ranges(date_str: str, exempt_ranges: List[Dict]) -> bool:
    """True if date falls in any inclusive {start, end} range on the listing."""
    d = _parse_date(date_str)
    if d is None:
        return False
    for item in exempt_ranges:
        start = _parse_date(str(item.get("start", "")))
        end = _parse_date(str(item.get("end", "")))
        if start is not None and end is not None and start <= d <= end:
            return True
    return False


def batna_floor_from_entry_for_date(entry: Dict, date_str: str, prop_data: Optional[Dict]) -> Optional[float]:
    """Resolve BATNA floor from a listing config entry and override date."""
    exempt_ranges = entry.get("batna_exempt_ranges")
    if exempt_ranges and is_date_in_batna_exempt_ranges(date_str, exempt_ranges):
        return None

    weekday_batna = entry.get("batna_weekday")
    weekend_batna = entry.get("batna_weekend")
    if weekday_batna is not None and weekend_batna is not None:
        try:
            weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
        except (ValueError, TypeError):
            return None
        if is_weekend_day(weekday):
            return float(weekend_batna)
        return float(weekday_batna)

    if entry.get("batna") is not None:
        try:
            weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
        except (ValueError, TypeError):
            return None
        return float(three_tier_batna_floor(float(entry["batna"]), weekday))
    return None


def batna_floor_for_date(
    listing_id: str, date_str: str, prop_config: Dict
) -> Optional[float]:
    """
    Resolve BATNA floor for one override date.
    batna_exempt_ranges: no floor for those dates (5% only).
    batna_weekday/batna_weekend: Sun-Thu / Fri-Sat (Blue Ridge).
    batna only: Mon-Wed base; Thu/Sun +15%; Fri/Sat +15% over Thu/Sun.
    """
    entry, prop_data = get_listing_config_entry(listing_id, prop_config)
    if not entry:
        return None
    return batna_floor_from_entry_for_date(entry, date_str, prop_data)


def calculate_adjusted_price(
    price: float, increase: bool = True, adjustment_percentage: float = 5
) -> float:
    """Apply +/- adjustment_percentage to price (no BATNA floor)."""
    if increase:
        return price * (1 + adjustment_percentage / 100)
    return price * (1 - adjustment_percentage / 100)


def apply_adjustment_with_batna(
    old_price: float,
    increase: bool,
    batna_floor: Optional[float],
    adjustment_percentage: float = 5,
) -> Tuple[int, bool]:
    """
    Adjust price then enforce BATNA floor on the result (increase or decrease).

    Returns:
        (final_price_int, was_clamped_to_batna)
    """
    adjusted = calculate_adjusted_price(
        old_price, increase=increase, adjustment_percentage=adjustment_percentage
    )
    if batna_floor is not None and adjusted < batna_floor:
        return int(batna_floor), True
    return int(adjusted), False
