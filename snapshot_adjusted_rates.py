#!/usr/bin/env python3
"""
Snapshot live PriceLabs rates for dates recorded in the adjustment ledger.

Use before/after evening ±5% runs to diff rates later.

Examples:
    python snapshot_adjusted_rates.py
    python snapshot_adjusted_rates.py --run-day 2026-08-06 --direction decrease
    python snapshot_adjusted_rates.py --label morning_pre_evening
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from pricelabs_tool.api_client import PriceLabsAPI
from pricelabs_tool.ledger_store import get_ledger_store, resolve_ledger_backend
from pricelabs_tool.property_config import listing_to_property, load_property_config
from pricelabs_tool.run_guard import AdjustmentLedger, run_day_local

load_dotenv(".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "rate_snapshots"


def _listing_meta(prop_config: Dict) -> Dict[str, Dict[str, str]]:
    """Map listing_id -> {name, pms, property_key, property_name}."""
    meta: Dict[str, Dict[str, str]] = {}
    for prop_key, prop_data in prop_config.items():
        if not isinstance(prop_data, dict):
            continue
        pms = str(prop_data.get("pms") or "")
        prop_name = str(prop_data.get("name") or prop_key)
        for entry in prop_data.get("listings", []):
            lid = str(entry.get("id", ""))
            if not lid:
                continue
            meta[lid] = {
                "name": str(entry.get("name") or lid),
                "pms": pms,
                "property_key": prop_key,
                "property_name": prop_name,
            }
    return meta


def _direction_label(direction: str) -> str:
    if direction == "increase":
        return "increase_+5pct"
    if direction == "decrease":
        return "decrease_-5pct"
    return direction


def collect_ledger_adjustments(
    ledger: AdjustmentLedger,
    listing_ids: List[str],
    run_day: str,
    direction: Optional[str],
) -> List[Dict[str, Any]]:
    """Load verified adjustment records for run_day (optionally one direction)."""
    return ledger.iter_verified_records(
        run_day, direction=direction, listing_ids=listing_ids
    )


def _fixed_price_by_date(overrides: List[Dict]) -> Dict[str, int]:
    by_date: Dict[str, int] = {}
    for item in overrides:
        if item.get("price_type") != "fixed":
            continue
        d = item.get("date")
        if not d:
            continue
        try:
            by_date[str(d)] = int(float(item.get("price", 0)))
        except (TypeError, ValueError):
            continue
    return by_date


def build_snapshot(
    api: PriceLabsAPI,
    ledger_records: List[Dict[str, Any]],
    meta_by_id: Dict[str, Dict[str, str]],
    prop_config: Dict,
    run_day: str,
    direction_filter: Optional[str],
    label: Optional[str],
) -> Dict[str, Any]:
    by_listing: Dict[str, List[Dict]] = defaultdict(list)
    for record in ledger_records:
        by_listing[str(record["listing_id"])].append(record)

    rows: List[Dict[str, Any]] = []
    missing_live = 0
    for listing_id, records in sorted(by_listing.items()):
        meta = meta_by_id.get(listing_id, {})
        pms = meta.get("pms") or None
        prop_key, prop_name = listing_to_property(listing_id, prop_config)
        try:
            payload = api.get_listing_overrides(listing_id, pms=pms)
            live_by_date = _fixed_price_by_date(payload.get("overrides", []))
        except Exception as e:
            logger.error("Failed to pull overrides for %s: %s", listing_id, e)
            for record in records:
                rows.append({
                    "listing_id": listing_id,
                    "listing_name": meta.get("name", listing_id),
                    "property_key": prop_key,
                    "property_name": prop_name,
                    "date": record.get("date"),
                    "live_price": None,
                    "pull_error": str(e),
                    "ledger_direction": record.get("direction"),
                    "ledger_adjustment": _direction_label(str(record.get("direction"))),
                    "ledger_price_before": record.get("price_before"),
                    "ledger_price_after": record.get("price_after"),
                    "ledger_run_day": record.get("run_day"),
                    "ledger_recorded_at": record.get("recorded_at"),
                })
            continue

        for record in sorted(records, key=lambda r: str(r.get("date", ""))):
            override_date = str(record.get("date", ""))
            live = live_by_date.get(override_date)
            if live is None:
                missing_live += 1
            rows.append({
                "listing_id": listing_id,
                "listing_name": meta.get("name", listing_id),
                "property_key": prop_key,
                "property_name": prop_name,
                "date": override_date,
                "live_price": live,
                "ledger_direction": record.get("direction"),
                "ledger_adjustment": _direction_label(str(record.get("direction"))),
                "ledger_price_before": record.get("price_before"),
                "ledger_price_after": record.get("price_after"),
                "ledger_run_day": record.get("run_day"),
                "ledger_recorded_at": record.get("recorded_at"),
            })

    directions_present = sorted({
        str(r.get("ledger_direction")) for r in rows if r.get("ledger_direction")
    })
    if direction_filter:
        adjustment_mark = _direction_label(direction_filter)
    elif len(directions_present) == 1:
        adjustment_mark = _direction_label(directions_present[0])
    else:
        adjustment_mark = "mixed"

    now = datetime.now(timezone.utc)
    return {
        "snapshot_at": now.isoformat().replace("+00:00", "Z"),
        "snapshot_date": now.date().isoformat(),
        "snapshot_timestamp_utc": now.strftime("%Y%m%d_%H%M%SZ"),
        "run_day": run_day,
        "adjustment": adjustment_mark,
        "adjustment_directions": directions_present,
        "label": label,
        "ledger_backend": get_ledger_store().backend_name,
        "listing_count": len(by_listing),
        "rate_count": len(rows),
        "missing_live_count": missing_live,
        "rates": rows,
    }


def write_snapshot(snapshot: Dict[str, Any]) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = snapshot["snapshot_timestamp_utc"]
    adjustment = snapshot["adjustment"]
    label = snapshot.get("label")
    parts = [stamp, adjustment]
    if label:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(label))
        parts.append(safe)
    path = SNAPSHOT_DIR / f"{'_'.join(parts)}.json"
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot live rates for ledger-adjusted listing/dates."
    )
    parser.add_argument(
        "--run-day",
        default=run_day_local(),
        help="Ledger run day to include (default: today local)",
    )
    parser.add_argument(
        "--direction",
        choices=["increase", "decrease"],
        default=None,
        help="Only include this ledger direction (default: both)",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional tag in the filename (e.g. morning_pre_evening)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prop_config = load_property_config()
    meta_by_id = _listing_meta(prop_config)
    listing_ids = sorted(meta_by_id.keys())

    logger.info("Ledger backend mode: %s", resolve_ledger_backend())
    ledger = AdjustmentLedger()
    logger.info("Using ledger: %s", ledger.backend_name)
    logger.info(
        "Collecting verified ledger rows for run_day=%s direction=%s",
        args.run_day,
        args.direction or "both",
    )

    ledger_records = collect_ledger_adjustments(
        ledger, listing_ids, args.run_day, args.direction
    )
    if not ledger_records:
        logger.error(
            "No verified ledger adjustments found for run_day=%s direction=%s",
            args.run_day,
            args.direction or "both",
        )
        return 1

    logger.info(
        "Found %s ledger row(s) across %s listing(s); pulling live PriceLabs rates...",
        len(ledger_records),
        len({r["listing_id"] for r in ledger_records}),
    )

    api = PriceLabsAPI()
    snapshot = build_snapshot(
        api,
        ledger_records,
        meta_by_id,
        prop_config,
        run_day=args.run_day,
        direction_filter=args.direction,
        label=args.label,
    )
    path = write_snapshot(snapshot)
    logger.info(
        "Wrote snapshot %s (%s rates, adjustment=%s)",
        path,
        snapshot["rate_count"],
        snapshot["adjustment"],
    )
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
