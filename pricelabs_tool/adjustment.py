"""Compute price adjustments and BATNA floors for listing overrides."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pricelabs_tool.batna import (
    apply_adjustment_with_batna,
    batna_floor_for_date,
    calculate_adjusted_price,
)
from pricelabs_tool.bookings import should_skip_booked_date
from pricelabs_tool.property_config import (
    is_date_in_valid_range,
    listing_to_property,
    listing_units,
)


def _day_label(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")
    except (ValueError, TypeError):
        return ""


def compute_listing_adjustments(
    listing: Dict,
    all_pulled: List[Dict],
    prop_config: Dict,
    increase: bool,
    adjustment_percentage: float = 5,
    booking_by_date: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build override payloads and preview rows for one listing.
    Does not call the PriceLabs API.
    """
    listing_id = str(listing.get("id"))
    total_units = listing_units(listing_id, prop_config)
    adjusted_overrides: List[Dict] = []
    preview_rows: List[Dict[str, Any]] = []
    skipped = {"not_fixed": 0, "date_range": 0, "bad_price": 0, "booked": 0}
    batna_clamped_count = 0

    for override in all_pulled:
        if override.get("price_type") != "fixed":
            skipped["not_fixed"] += 1
            continue
        override_date = override.get("date", "")
        if not is_date_in_valid_range(override_date):
            skipped["date_range"] += 1
            continue
        old_price = float(override.get("price", 0))
        if old_price <= 0:
            skipped["bad_price"] += 1
            continue
        if booking_by_date is not None:
            booking_info = booking_by_date.get(override_date)
            if isinstance(booking_info, dict):
                booking_status = booking_info.get("booking_status")
                available = booking_info.get("available")
                multi_unit_occupancy = booking_info.get("multi_unit_occupancy")
            else:
                booking_status = booking_info
                available = None
                multi_unit_occupancy = None
            if should_skip_booked_date(
                booking_status,
                total_units=total_units,
                available=available,
                multi_unit_occupancy=multi_unit_occupancy,
            ):
                skipped["booked"] += 1
                continue

        floor = batna_floor_for_date(listing_id, override_date, prop_config)
        adjusted_raw = calculate_adjusted_price(
            old_price, increase=increase, adjustment_percentage=adjustment_percentage
        )
        new_price, clamped = apply_adjustment_with_batna(
            old_price,
            increase=increase,
            batna_floor=floor,
            adjustment_percentage=adjustment_percentage,
        )
        if clamped:
            batna_clamped_count += 1

        preview_rows.append(
            {
                "date": override_date,
                "day": _day_label(override_date),
                "old_price": old_price,
                "adjusted_5pct": int(adjusted_raw),
                "batna_floor": floor,
                "new_price": new_price,
                "clamped": clamped,
            }
        )
        adjusted_overrides.append(
            {
                "date": override_date,
                "price": str(new_price),
                "price_type": "fixed",
                "currency": override.get("currency", "USD"),
                "min_stay": override.get("min_stay", 1),
            }
        )

    prop_key = listing_to_property(listing_id, prop_config)[0]
    prop_data = prop_config.get(prop_key) if isinstance(prop_config.get(prop_key), dict) else {}

    return {
        "adjusted_overrides": adjusted_overrides,
        "preview_rows": preview_rows,
        "would_update": len(adjusted_overrides),
        "batna_clamped_count": batna_clamped_count,
        "skipped": skipped,
        "update_children": prop_data.get("update_children", False),
        "prop_key": prop_key,
    }
