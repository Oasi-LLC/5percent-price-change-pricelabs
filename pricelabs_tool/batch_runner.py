"""Headless batch processing for PriceLabs price adjustments."""

import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

from pricelabs_tool.adjustment import compute_listing_adjustments
from pricelabs_tool.api_client import PriceLabsAPI
from pricelabs_tool.property_config import (
    exclude_listings_not_in_config,
    extract_parent_listing_id,
    listing_pms,
    load_property_config,
    mirror_rates_from_listing_id,
    mirror_targets_for_source,
    partition_adjust_and_mirror_listings,
    split_children_of_selected_update_children_parents,
)
from pricelabs_tool.run_guard import (
    AdjustmentLedger,
    AdjustmentRunInProgressError,
    adjustment_run_lock,
    filter_adjustments_for_idempotency,
    run_day_local,
)
from pricelabs_tool.verify import verify_listing_overrides

logger = logging.getLogger(__name__)

ADJUSTMENT_PERCENTAGE = 5
MAX_RETRIES_PER_LISTING = 3
RETRY_BACKOFF_SECONDS = (5, 10)

ProgressCallback = Optional[Callable[[str], None]]


def fetch_active_listings() -> List[Dict]:
    """Fetch active, push-enabled listings from PriceLabs."""
    api_client = PriceLabsAPI()
    listings = api_client.get_listings()
    return [
        listing
        for listing in listings
        if not listing.get("isHidden", True) and listing.get("push_enabled", False)
    ]


def fetch_configured_listings() -> Tuple[List[Dict], int]:
    """
    Fetch active listings and keep only those in properties_config.yaml.

    Returns:
        (configured_listings, excluded_count)
    """
    raw_listings = fetch_active_listings()
    prop_config = load_property_config()
    return exclude_listings_not_in_config(raw_listings, prop_config)


def _format_verification_errors(mismatches: List[Dict]) -> str:
    parts = []
    for item in mismatches[:5]:
        actual = item.get("actual")
        actual_label = f"${actual}" if actual is not None else "missing"
        parts.append(
            f"{item['date']}: expected ${item['expected']}, got {actual_label}"
        )
    if len(mismatches) > 5:
        parts.append(f"…and {len(mismatches) - 5} more")
    return "; ".join(parts)


def _skipped_count(skipped: Dict) -> int:
    return (
        skipped["not_fixed"]
        + skipped["date_range"]
        + skipped["bad_price"]
        + skipped.get("booked", 0)
    )


def _format_skipped_breakdown(skipped: Dict) -> str:
    parts = []
    if skipped.get("booked"):
        parts.append(f"{skipped['booked']} booked")
    if skipped.get("not_fixed"):
        parts.append(f"{skipped['not_fixed']} non-fixed")
    if skipped.get("date_range"):
        parts.append(f"{skipped['date_range']} out of date range")
    if skipped.get("bad_price"):
        parts.append(f"{skipped['bad_price']} bad price")
    return ", ".join(parts)


def _process_listing(
    listing: Dict,
    prop_config: Dict,
    increase: bool,
    adjustment_percentage: float,
    run_day: str,
    ledger: AdjustmentLedger,
    booking_by_date: Optional[Dict] = None,
) -> Dict:
    """Fetch, idempotency-filter, apply once, verify, and record one listing."""
    api_client = PriceLabsAPI()
    listing_id = str(listing["id"])

    overrides = api_client.get_listing_overrides(listing_id, pms=listing.get("pms"))
    all_pulled = overrides.get("overrides", [])
    computed = compute_listing_adjustments(
        listing,
        all_pulled,
        prop_config,
        increase=increase,
        adjustment_percentage=adjustment_percentage,
        booking_by_date=booking_by_date,
        ledger=ledger,
    )
    skipped = computed["skipped"]
    num_skipped = _skipped_count(skipped)

    if computed["would_update"] == 0:
        msg = "No overrides in valid range (fixed, today or future, ≤1 year) to update"
        if all_pulled:
            breakdown = _format_skipped_breakdown(skipped)
            msg += f". Pulled {len(all_pulled)} total (skipped: {breakdown})"
        return {
            "id": listing_id,
            "name": listing["name"],
            "status": "skipped",
            "message": msg,
        }

    to_apply, idem_stats = filter_adjustments_for_idempotency(
        listing_id,
        computed["preview_rows"],
        computed["adjusted_overrides"],
        increase,
        run_day,
        ledger,
    )

    if not to_apply:
        already = idem_stats["skip_already_done"]
        no_change = idem_stats["skip_no_change"]
        return {
            "id": listing_id,
            "name": listing["name"],
            "status": "skipped",
            "message": (
                f"All {computed['would_update']} qualifying date(s) already at target "
                f"({already} verified today, {no_change} unchanged)"
            ),
            "already_adjusted_count": already + no_change,
        }

    preview_by_date = {row["date"]: row for row in computed["preview_rows"]}
    expected_by_date = {item["date"]: int(item["price"]) for item in to_apply}
    batna_clamped_applied = sum(
        1 for item in to_apply if preview_by_date[item["date"]].get("clamped")
    )

    if computed["update_children"]:
        logger.info(
            "listing_id=%s name=%s update_children=true (property=%s)",
            listing.get("id"),
            listing.get("name"),
            computed["prop_key"],
        )

    api_client.update_listing_overrides(
        listing_id,
        to_apply,
        pms=listing.get("pms"),
        update_children=computed["update_children"],
    )

    verified, mismatches = verify_listing_overrides(
        api_client,
        listing_id,
        expected_by_date,
        pms=listing.get("pms"),
    )
    if not verified:
        return {
            "id": listing_id,
            "name": listing["name"],
            "status": "error",
            "message": (
                "Post-adjustment verification failed: "
                + _format_verification_errors(mismatches)
            ),
            "verification_failed": True,
            "verification_mismatches": mismatches,
        }

    for override in to_apply:
        row = preview_by_date[override["date"]]
        ledger.record_verified(
            listing_id,
            override["date"],
            "increase" if increase else "decrease",
            run_day,
            int(row["old_price"]),
            int(override["price"]),
        )
        ledger.set_anchor(
            listing_id,
            override["date"],
            int(row["reference_price"]),
            row.get("state_after_apply", "neutral"),
        )

    return {
        "id": listing_id,
        "name": listing["name"],
        "status": "success",
        "dates_updated": len(to_apply),
        "dates_verified": len(to_apply),
        "already_adjusted_count": (
            idem_stats["skip_already_done"] + idem_stats["skip_no_change"]
        ),
        "batna_clamped_count": batna_clamped_applied,
        "skipped_count": num_skipped,
        "skipped_not_fixed": skipped["not_fixed"],
        "skipped_date_range": skipped["date_range"],
        "skipped_bad_price": skipped["bad_price"],
        "skipped_booked": skipped.get("booked", 0),
        "applied_overrides": to_apply,
    }


def _mirror_rates_from_source(
    source_listing_id: str,
    applied_overrides: List[Dict],
    prop_config: Dict,
    api_client: PriceLabsAPI,
) -> List[Dict]:
    """Copy applied override prices from source listing to configured mirror targets."""
    if not applied_overrides:
        return []

    targets = mirror_targets_for_source(source_listing_id, prop_config)
    results: List[Dict] = []
    for target in targets:
        target_id = target["id"]
        target_pms = target.get("pms") or listing_pms(target_id, prop_config)
        try:
            payload = api_client.get_listing_overrides(target_id, pms=target_pms)
        except Exception as e:
            results.append({
                "id": target_id,
                "name": target.get("name", target_id),
                "status": "error",
                "message": f"Mirror copy failed (could not pull target): {e}",
                "mirrored_from": source_listing_id,
            })
            continue

        existing = {
            item.get("date"): item
            for item in payload.get("overrides", [])
            if item.get("date")
        }
        to_mirror: List[Dict] = []
        for override in applied_overrides:
            override_date = override["date"]
            new_price = int(override["price"])
            existing_row = existing.get(override_date)
            if existing_row and int(float(existing_row.get("price", 0))) == new_price:
                continue
            to_mirror.append({
                "date": override_date,
                "price": str(new_price),
                "price_type": "fixed",
                "currency": (existing_row or override).get("currency", "USD"),
                "min_stay": (existing_row or override).get("min_stay", 1),
            })

        if not to_mirror:
            results.append({
                "id": target_id,
                "name": target.get("name", target_id),
                "status": "skipped",
                "message": (
                    f"Mirror from {source_listing_id}: all {len(applied_overrides)} date(s) "
                    "already match source prices"
                ),
                "mirrored_from": source_listing_id,
                "already_adjusted_count": len(applied_overrides),
            })
            continue

        try:
            expected_by_date = {item["date"]: int(item["price"]) for item in to_mirror}
            api_client.update_listing_overrides(
                target_id, to_mirror, pms=target_pms, update_children=False
            )
            verified, mismatches = verify_listing_overrides(
                api_client, target_id, expected_by_date, pms=target_pms
            )
        except Exception as e:
            results.append({
                "id": target_id,
                "name": target.get("name", target_id),
                "status": "error",
                "message": f"Mirror copy push failed: {e}",
                "mirrored_from": source_listing_id,
            })
            continue

        if not verified:
            results.append({
                "id": target_id,
                "name": target.get("name", target_id),
                "status": "error",
                "message": (
                    "Mirror copy verification failed: "
                    + _format_verification_errors(mismatches)
                ),
                "mirrored_from": source_listing_id,
                "verification_failed": True,
            })
            continue

        results.append({
            "id": target_id,
            "name": target.get("name", target_id),
            "status": "success",
            "message": (
                f"Mirrored {len(to_mirror)} date(s) from source {source_listing_id}"
            ),
            "mirrored_from": source_listing_id,
            "dates_updated": len(to_mirror),
            "dates_verified": len(to_mirror),
        })
    return results


def batch_update(
    listings: List[Dict],
    increase: bool,
    adjustment_percentage: float = ADJUSTMENT_PERCENTAGE,
    batch_size: int = 10,
    delay: int = 2,
    per_listing_delay: int = 2,
    progress_callback: ProgressCallback = None,
    use_run_lock: bool = True,
) -> List[Dict]:
    """Process listings in batches and upload adjusted overrides to PriceLabs."""
    if use_run_lock:
        with adjustment_run_lock(increase) as ledger_repo:
            return _batch_update_inner(
                listings,
                increase,
                adjustment_percentage,
                batch_size,
                delay,
                per_listing_delay,
                progress_callback,
                ledger_repo=ledger_repo,
            )
    return _batch_update_inner(
        listings,
        increase,
        adjustment_percentage,
        batch_size,
        delay,
        per_listing_delay,
        progress_callback,
    )


def _batch_update_inner(
    listings: List[Dict],
    increase: bool,
    adjustment_percentage: float,
    batch_size: int,
    delay: int,
    per_listing_delay: int,
    progress_callback: ProgressCallback,
    ledger_repo=None,
) -> List[Dict]:
    prop_config = load_property_config()
    ledger = AdjustmentLedger(ledger_repo)
    logger.info("Adjustment idempotency ledger: %s", ledger.backend_name)
    run_day = run_day_local()
    results: List[Dict] = []

    listings, auto_skipped_children = split_children_of_selected_update_children_parents(
        listings, prop_config
    )
    listings, mirror_only_selected = partition_adjust_and_mirror_listings(
        listings, prop_config
    )
    for child in auto_skipped_children:
        parent_id = extract_parent_listing_id(child)
        msg = "Auto-skipped child listing: selected parent has update_children=true"
        if parent_id:
            msg += f" (parent_id={parent_id})"
        results.append({
            "id": child["id"],
            "name": child.get("name", str(child.get("id"))),
            "status": "skipped",
            "message": msg,
        })

    for mirror_listing in mirror_only_selected:
        source_id = mirror_rates_from_listing_id(str(mirror_listing.get("id")), prop_config)
        results.append({
            "id": mirror_listing["id"],
            "name": mirror_listing.get("name", str(mirror_listing.get("id"))),
            "status": "skipped",
            "message": (
                f"Mirror-only listing: rates copy from source {source_id} when that "
                "listing is adjusted (not ±5% adjusted independently)"
            ),
        })

    total = len(listings)
    for i in range(0, total, batch_size):
        batch = listings[i : i + batch_size]
        batch_msg = (
            f"Processing batch {i // batch_size + 1} of "
            f"{(total + batch_size - 1) // batch_size} ({len(batch)} listings)"
        )
        logger.info(batch_msg)
        if progress_callback:
            progress_callback(batch_msg)

        api_client = PriceLabsAPI()
        try:
            batch_booking_status = api_client.get_booking_status_by_listing(batch)
        except Exception as e:
            logger.error("Failed to fetch booking status for batch: %s", e)
            for listing in batch:
                results.append({
                    "id": listing["id"],
                    "name": listing["name"],
                    "status": "error",
                    "message": f"Could not fetch booking status: {e}",
                })
            time.sleep(per_listing_delay * len(batch))
            if i + batch_size < total:
                time.sleep(delay)
            continue

        for listing in batch:
            last_error = None
            booking_by_date = batch_booking_status.get(str(listing.get("id")), {})
            for attempt in range(MAX_RETRIES_PER_LISTING):
                try:
                    result = _process_listing(
                        listing,
                        prop_config,
                        increase,
                        adjustment_percentage,
                        run_day,
                        ledger,
                        booking_by_date=booking_by_date,
                    )
                    results.append(result)
                    if result.get("status") == "success":
                        applied = result.get("applied_overrides") or []
                        if applied:
                            mirror_results = _mirror_rates_from_source(
                                str(listing["id"]),
                                applied,
                                prop_config,
                                api_client,
                            )
                            results.extend(mirror_results)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES_PER_LISTING - 1:
                        wait = (
                            RETRY_BACKOFF_SECONDS[attempt]
                            if attempt < len(RETRY_BACKOFF_SECONDS)
                            else 10
                        )
                        logger.warning(
                            "Listing %s attempt %s failed (%s); retrying in %ss",
                            listing.get("id"),
                            attempt + 1,
                            e,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        results.append({
                            "id": listing["id"],
                            "name": listing["name"],
                            "status": "error",
                            "message": str(last_error),
                        })
                        break
            time.sleep(per_listing_delay)
        if i + batch_size < total:
            time.sleep(delay)

    ledger.save()
    return results


def summarize_results(results: List[Dict]) -> Dict:
    """Aggregate batch_update results into summary counts."""
    successful = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] == "error"]
    skipped = [r for r in results if r["status"] == "skipped"]
    dates_updated = sum(r.get("dates_updated", 0) for r in successful)
    dates_verified = sum(r.get("dates_verified", 0) for r in successful)
    batna_clamped = sum(r.get("batna_clamped_count", 0) for r in successful)
    already_adjusted = sum(r.get("already_adjusted_count", 0) for r in results)
    skipped_booked = sum(r.get("skipped_booked", 0) for r in results)
    verification_failed = [r for r in failed if r.get("verification_failed")]
    return {
        "total": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "skipped": len(skipped),
        "dates_updated": dates_updated,
        "dates_verified": dates_verified,
        "batna_clamped": batna_clamped,
        "already_adjusted": already_adjusted,
        "skipped_booked": skipped_booked,
        "verification_failed": len(verification_failed),
        "successful_listings": successful,
        "failed_listings": failed,
        "skipped_listings": skipped,
    }


__all__ = [
    "AdjustmentRunInProgressError",
    "ADJUSTMENT_PERCENTAGE",
    "batch_update",
    "fetch_active_listings",
    "fetch_configured_listings",
    "summarize_results",
]
