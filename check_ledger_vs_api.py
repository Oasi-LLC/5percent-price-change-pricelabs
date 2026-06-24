#!/usr/bin/env python3
"""
Compare adjustment ledger records against live PriceLabs override API.

Use this when the ledger says a listing was adjusted but PriceLabs UI looks unchanged.

Usage:
    python3 check_ledger_vs_api.py /path/to/ledger.json
    python3 check_ledger_vs_api.py /path/to/ledger.json --property onera
    python3 check_ledger_vs_api.py /path/to/ledger.json --listing 203812___362535
    python3 check_ledger_vs_api.py /path/to/ledger.json --samples 30
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from pricelabs_tool.api_client import PriceLabsAPI
from pricelabs_tool.batch_runner import fetch_active_listings
from pricelabs_tool.property_config import listing_to_property, load_property_config

load_dotenv()

RUN_DAY = "2026-06-24"
DIRECTION = "increase"


def _fixed_by_date(overrides: List[Dict]) -> Dict[str, int]:
    by_date: Dict[str, int] = {}
    for item in overrides:
        if item.get("price_type") != "fixed":
            continue
        date = item.get("date")
        if not date:
            continue
        try:
            by_date[date] = int(float(item.get("price", 0)))
        except (TypeError, ValueError):
            continue
    return by_date


def load_ledger_records(path: Path, run_day: str, direction: str) -> Dict[str, List[Dict]]:
    with open(path) as f:
        payload = json.load(f)
    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for record in payload.get("records", []):
        if record.get("run_day") != run_day or record.get("direction") != direction:
            continue
        grouped[str(record["listing_id"])].append(record)
    return grouped


def sample_records(records: List[Dict], n: int) -> List[Dict]:
    if len(records) <= n:
        return list(records)
    return random.sample(records, n)


def check_listing(
    api: PriceLabsAPI,
    listing_id: str,
    records: List[Dict],
    pms: Optional[str],
    sample_size: int,
) -> Dict:
    sampled = sample_records(records, sample_size)
    response = api.get_listing_overrides(listing_id, pms=pms)
    actual = _fixed_by_date(response.get("overrides", []))

    matches = 0
    reverted = 0
    missing = 0
    other = 0
    examples: List[str] = []

    for record in sampled:
        date = record["date"]
        expected = int(record["price_after"])
        before = int(record["price_before"])
        current = actual.get(date)
        if current == expected:
            matches += 1
        elif current == before:
            reverted += 1
            if len(examples) < 5:
                examples.append(
                    f"  {date}: ledger {before}->{expected}, API now {current} (reverted to before)"
                )
        elif current is None:
            missing += 1
            if len(examples) < 5:
                examples.append(
                    f"  {date}: ledger {before}->{expected}, API has no fixed override on this date"
                )
        else:
            other += 1
            if len(examples) < 5:
                examples.append(
                    f"  {date}: ledger {before}->{expected}, API now {current} (unexpected)"
                )

    total = len(sampled)
    return {
        "listing_id": listing_id,
        "sampled": total,
        "ledger_dates": len(records),
        "matches": matches,
        "reverted": reverted,
        "missing": missing,
        "other": other,
        "match_pct": round(100 * matches / total, 1) if total else 0,
        "examples": examples,
        "pms": pms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare ledger vs live PriceLabs overrides")
    parser.add_argument("ledger", type=Path, help="Path to ledger.json")
    parser.add_argument("--run-day", default=RUN_DAY)
    parser.add_argument("--direction", default=DIRECTION, choices=["increase", "decrease"])
    parser.add_argument("--property", action="append", default=[], help="Property key(s) from yaml, e.g. onera, lafavezion")
    parser.add_argument("--listing", action="append", default=[], help="Specific listing id(s)")
    parser.add_argument("--samples", type=int, default=20, help="Dates to sample per listing")
    args = parser.parse_args()

    grouped = load_ledger_records(args.ledger, args.run_day, args.direction)
    if not grouped:
        print(f"No ledger records for {args.direction} on {args.run_day}")
        return 1

    prop_config = load_property_config()
    api_listings = {str(item["id"]): item for item in fetch_active_listings()}

    targets: List[Tuple[str, List[Dict]]] = []
    for listing_id, records in sorted(grouped.items()):
        prop_key, _ = listing_to_property(listing_id, prop_config)
        if args.listing and listing_id not in args.listing:
            continue
        if args.property and prop_key not in args.property:
            continue
        targets.append((listing_id, records))

    if not targets:
        print("No listings matched filters.")
        return 1

    api = PriceLabsAPI()
    print(
        f"Checking {len(targets)} listing(s) from ledger "
        f"({args.direction} on {args.run_day}), {args.samples} sample date(s) each\n"
    )

    summary = {"full_match": 0, "partial": 0, "reverted": 0, "missing_heavy": 0}
    for listing_id, records in targets:
        listing = api_listings.get(listing_id, {})
        prop_key, prop_name = listing_to_property(listing_id, prop_config)
        pms = listing.get("pms")
        name = listing.get("name", listing_id)

        result = check_listing(api, listing_id, records, pms=pms, sample_size=args.samples)
        status = "OK"
        if result["matches"] == result["sampled"]:
            status = "OK (API matches ledger)"
            summary["full_match"] += 1
        elif result["reverted"] == result["sampled"]:
            status = "REVERTED (API back to pre-run prices)"
            summary["reverted"] += 1
        elif result["missing"] >= result["sampled"] // 2:
            status = "MISSING (fixed overrides not found in API)"
            summary["missing_heavy"] += 1
        else:
            status = "PARTIAL / MIXED"
            summary["partial"] += 1

        print(
            f"[{status}] {prop_name} / {name}\n"
            f"  id={listing_id} pms={pms or '(none)'} ledger_dates={result['ledger_dates']}\n"
            f"  sample: {result['matches']} match, {result['reverted']} reverted, "
            f"{result['missing']} missing, {result['other']} other "
            f"({result['match_pct']}% match)"
        )
        for line in result["examples"]:
            print(line)
        print()

    print("Summary:")
    print(f"  Full API match:     {summary['full_match']}")
    print(f"  Reverted:           {summary['reverted']}")
    print(f"  Missing overrides:  {summary['missing_heavy']}")
    print(f"  Partial/mixed:      {summary['partial']}")
    print()
    print(
        "Interpretation:\n"
        "  - OK: API still has the adjusted fixed overrides (ledger is accurate).\n"
        "  - REVERTED: changes were applied at run time but are gone now (PMS/sync may have overwritten).\n"
        "  - MISSING: API has no fixed override on those dates (check Customizations vs Review Prices in UI).\n"
        "  - PARTIAL: some dates stuck, some did not — inspect examples above."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
