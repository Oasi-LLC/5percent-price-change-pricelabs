"""Post-adjustment verification against PriceLabs API."""

import logging
import time
from typing import Dict, List, Tuple

from pricelabs_tool.api_client import PriceLabsAPI

logger = logging.getLogger(__name__)

VERIFY_DELAY_SECONDS = 1


def _fixed_prices_by_date(overrides: List[Dict]) -> Dict[str, int]:
    by_date: Dict[str, int] = {}
    for override in overrides:
        if override.get("price_type") != "fixed":
            continue
        override_date = override.get("date")
        if not override_date:
            continue
        try:
            by_date[override_date] = int(float(override.get("price", 0)))
        except (TypeError, ValueError):
            continue
    return by_date


def verify_listing_overrides(
    api_client: PriceLabsAPI,
    listing_id: str,
    expected_by_date: Dict[str, int],
    pms: str = None,
    delay_seconds: float = VERIFY_DELAY_SECONDS,
) -> Tuple[bool, List[Dict]]:
    """
    Re-fetch overrides and confirm each date matches the expected price.

    Returns:
        (all_match, mismatches) where each mismatch has date, expected, actual
    """
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    response = api_client.get_listing_overrides(listing_id, pms=pms)
    actual_by_date = _fixed_prices_by_date(response.get("overrides", []))

    mismatches: List[Dict] = []
    for override_date, expected_price in expected_by_date.items():
        actual_price = actual_by_date.get(override_date)
        if actual_price != expected_price:
            mismatches.append({
                "date": override_date,
                "expected": expected_price,
                "actual": actual_price,
            })

    if mismatches:
        logger.error(
            "Verification failed for listing %s: %s mismatch(es)",
            listing_id,
            len(mismatches),
        )
    return len(mismatches) == 0, mismatches
