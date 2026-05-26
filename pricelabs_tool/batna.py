"""BATNA floor resolution and price adjustment with minimum-rate clamping."""

from datetime import datetime
from typing import Dict, Optional, Tuple


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


def is_weekend_day(weekday: int) -> bool:
    """True for Friday/Saturday (weekday: Mon=0 .. Sun=6). Sun-Thu use weekday BATNA."""
    return weekday in (4, 5)


def batna_floor_from_entry_for_date(entry: Dict, date_str: str, prop_data: Optional[Dict]) -> Optional[float]:
    """Resolve BATNA floor from a listing config entry and override date."""
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
        return float(entry["batna"])
    return None


def batna_floor_for_date(
    listing_id: str, date_str: str, prop_config: Dict
) -> Optional[float]:
    """
    Resolve BATNA floor for one override date.
    SOS/Maya: batna_weekday (Sun-Thu) / batna_weekend (Fri-Sat).
    Others: flat batna.
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
