"""Booking status helpers for skipping booked dates."""

import re
from typing import Any, Dict, Optional, Tuple


_MULTI_UNIT_OCCUPANCY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def is_booked_status(booking_status: Optional[str]) -> bool:
    """True when PriceLabs booking_status indicates a booked night."""
    if not booking_status or not str(booking_status).strip():
        return False
    return "booked" in str(booking_status).lower()


def parse_multi_unit_occupancy(value: Any) -> Optional[Tuple[int, int]]:
    """Parse PriceLabs multi_unit_occupancy like '5/8' -> (booked, total)."""
    if value is None:
        return None
    match = _MULTI_UNIT_OCCUPANCY_RE.match(str(value))
    if not match:
        return None
    booked, total = int(match.group(1)), int(match.group(2))
    return booked, total


def is_fully_booked_multi_unit(
    multi_unit_occupancy: Any,
    *,
    available: Optional[bool] = None,
) -> bool:
    """True when all sellable units are booked for a multi-unit listing."""
    if available is False:
        return True
    parsed = parse_multi_unit_occupancy(multi_unit_occupancy)
    if not parsed:
        return False
    booked, total = parsed
    return total > 0 and booked >= total


def should_skip_booked_date(
    booking_status: Optional[str],
    *,
    total_units: int = 1,
    available: Optional[bool] = None,
    multi_unit_occupancy: Any = None,
) -> bool:
    """
    True when a date should be skipped because it cannot accept new bookings.

    Single-unit listings: any booked night is skipped (PriceLabs booking_status).
    Multi-unit listings: skip only when fully sold out. PriceLabs may report
    booking_status \"Booked\" when any unit has a reservation; use
    multi_unit_occupancy (e.g. '5/8') for sellout detection.
    """
    if total_units > 1:
        return is_fully_booked_multi_unit(
            multi_unit_occupancy,
            available=available,
        )
    return is_booked_status(booking_status)


def booking_info_by_date_from_rows(price_rows: list) -> Dict[str, Dict[str, Any]]:
    """Build date -> booking info map from POST /listing_prices data rows."""
    by_date: Dict[str, Dict[str, Any]] = {}
    for row in price_rows:
        date = row.get("date")
        if not date:
            continue
        info: Dict[str, Any] = {"booking_status": row.get("booking_status") or ""}
        if "available" in row:
            info["available"] = row.get("available")
        if "multi_unit_occupancy" in row:
            info["multi_unit_occupancy"] = row.get("multi_unit_occupancy")
        by_date[date] = info
    return by_date


def booking_status_by_date_from_rows(price_rows: list) -> Dict[str, str]:
    """Build date -> booking_status map from POST /listing_prices data rows."""
    return {
        date: info.get("booking_status") or ""
        for date, info in booking_info_by_date_from_rows(price_rows).items()
    }
