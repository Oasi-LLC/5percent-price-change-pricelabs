"""Booking status helpers for skipping booked dates."""

from typing import Dict, Optional


def is_booked_status(booking_status: Optional[str]) -> bool:
    """True when PriceLabs booking_status indicates a booked night."""
    if not booking_status or not str(booking_status).strip():
        return False
    return "booked" in str(booking_status).lower()


def booking_status_by_date_from_rows(price_rows: list) -> Dict[str, str]:
    """Build date -> booking_status map from POST /listing_prices data rows."""
    return {
        row["date"]: row.get("booking_status") or ""
        for row in price_rows
        if row.get("date")
    }
