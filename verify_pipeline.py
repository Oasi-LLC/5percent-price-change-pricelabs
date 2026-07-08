#!/usr/bin/env python3
"""
Pre-flight verification for the PriceLabs adjustment automation pipeline.

Safe by default: checks connectivity and previews changes without writing prices.

Usage:
    python verify_pipeline.py                    # full safe verification
    python verify_pipeline.py --test-slack       # also send a test Slack message
    python verify_pipeline.py --test-ledger-lock # exercise distributed lock acquire/release
    python verify_pipeline.py --live increase    # REAL run (same as run_adjustment.py)
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent


class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str = "", required: bool = True):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.required = required

    @property
    def status_label(self) -> str:
        if self.passed:
            return "PASS"
        return "FAIL" if self.required else "WARN"


def _mask(value: str) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def check_env() -> List[CheckResult]:
    results = []
    pricelabs = os.getenv("PRICELABS_API_KEY")
    slack = os.getenv("SLACK_WEBHOOK_URL")
    github = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    results.append(CheckResult(
        "PRICELABS_API_KEY",
        bool(pricelabs),
        _mask(pricelabs) if pricelabs else "Required for PriceLabs API",
    ))
    results.append(CheckResult(
        "SLACK_WEBHOOK_URL",
        bool(slack),
        _mask(slack) if slack else "Set in automation secrets for run summaries",
        required=False,
    ))
    results.append(CheckResult(
        "GITHUB_TOKEN",
        bool(github),
        _mask(github) if github else "Set in cloud automation secrets for shared idempotency ledger",
        required=False,
    ))

    from pricelabs_tool.ledger_store import resolve_ledger_backend, get_ledger_store

    backend = resolve_ledger_backend()
    store = get_ledger_store()
    results.append(CheckResult(
        "Ledger backend resolved",
        True,
        f"mode={backend}, store={store.backend_name}",
    ))
    return results


def check_unit_tests() -> CheckResult:
    cmd = [
        sys.executable,
        "-c",
        (
            "from pricelabs_tool.tests import test_batna, test_run_guard\n"
            "for mod in (test_batna, test_run_guard):\n"
            "    for name in sorted(dir(mod)):\n"
            "        if name.startswith('test_'):\n"
            "            getattr(mod, name)()\n"
            "print('ok')"
        ),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return CheckResult("Unit tests", True, "BATNA + run guard tests passed")
        return CheckResult("Unit tests", False, proc.stderr or proc.stdout)
    except Exception as e:
        return CheckResult("Unit tests", False, str(e))


def check_pricelabs_api() -> CheckResult:
    try:
        from pricelabs_tool.batch_runner import fetch_configured_listings

        listings, excluded = fetch_configured_listings()
        if not listings:
            return CheckResult(
                "PriceLabs API + config filter",
                False,
                f"0 configured listings ({excluded} excluded). Check API key and properties_config.yaml",
            )
        sample = ", ".join(l["name"] for l in listings[:3])
        if len(listings) > 3:
            sample += f", … (+{len(listings) - 3} more)"
        return CheckResult(
            "PriceLabs API + config filter",
            True,
            f"{len(listings)} configured listing(s), {excluded} excluded. Sample: {sample}",
        )
    except Exception as e:
        return CheckResult("PriceLabs API + config filter", False, str(e))


def check_dry_run_preview(direction: str, sample_limit: int = 8) -> CheckResult:
    """Fetch overrides and compute adjustments without posting (sampled listings)."""
    try:
        from pricelabs_tool.adjustment import compute_listing_adjustments
        from pricelabs_tool.api_client import PriceLabsAPI
        from pricelabs_tool.batch_runner import fetch_configured_listings
        from pricelabs_tool.property_config import load_property_config
        from pricelabs_tool.run_guard import (
            filter_adjustments_for_idempotency,
            run_day_local,
        )
        from pricelabs_tool.ledger_store import LedgerRepository, FileLedgerStore

        increase = direction == "increase"
        listings, _ = fetch_configured_listings()
        preview_listings = listings if sample_limit <= 0 else listings[:sample_limit]
        prop_config = load_property_config()
        api = PriceLabsAPI()

        with tempfile.TemporaryDirectory() as tmp:
            store = FileLedgerStore(path=Path(tmp) / "ledger.json")
            ledger_repo = LedgerRepository(store=store)
            from pricelabs_tool.run_guard import AdjustmentLedger
            ledger = AdjustmentLedger(repository=ledger_repo)

            total_dates = 0
            would_apply = 0
            would_skip = 0
            skipped_booked = 0
            sample_lines: List[str] = []
            errors = 0

            booking_batch = api.get_booking_status_by_listing(preview_listings)

            for listing in preview_listings:
                try:
                    listing_id = str(listing["id"])
                    booking_by_date = booking_batch.get(listing_id, {})
                    pulled = api.get_listing_overrides(
                        listing["id"], pms=listing.get("pms")
                    ).get("overrides", [])
                    computed = compute_listing_adjustments(
                        listing,
                        pulled,
                        prop_config,
                        increase=increase,
                        booking_by_date=booking_by_date,
                    )
                    to_apply, stats = filter_adjustments_for_idempotency(
                        str(listing["id"]),
                        computed["preview_rows"],
                        computed["adjusted_overrides"],
                        increase,
                        run_day_local(),
                        ledger,
                    )
                    total_dates += computed["would_update"]
                    skipped_booked += computed["skipped"].get("booked", 0)
                    would_apply += len(to_apply)
                    would_skip += stats["skip_already_done"] + stats["skip_no_change"]

                    if len(sample_lines) < 5 and computed["preview_rows"]:
                        row = computed["preview_rows"][0]
                        action = "apply" if to_apply else "skip"
                        sample_lines.append(
                            f"{listing['name']} {row['date']}: "
                            f"${int(row['old_price'])} → ${row['new_price']} ({action})"
                        )
                except Exception as e:
                    errors += 1
                    if len(sample_lines) < 8:
                        sample_lines.append(f"{listing.get('name')}: ERROR {e}")

        label = "increase (+5%)" if increase else "decrease (-5%)"
        sampled = len(preview_listings)
        total = len(listings)
        scope = f"{sampled}/{total} listings sampled" if sampled < total else f"{total} listings"
        detail = (
            f"{label} ({scope}): "
            f"{total_dates} qualifying dates, "
            f"{would_apply} would apply, "
            f"{would_skip} would skip (idempotency/no-op), "
            f"{skipped_booked} booked dates excluded"
        )
        if sample_lines:
            detail += "\n  Samples:\n  - " + "\n  - ".join(sample_lines)
        return CheckResult(f"Dry-run preview ({direction})", errors == 0, detail)
    except Exception as e:
        return CheckResult(f"Dry-run preview ({direction})", False, str(e))


def check_ledger_read_write() -> CheckResult:
    try:
        from pricelabs_tool.ledger_store import (
            LedgerRepository,
            get_ledger_store,
            resolve_ledger_backend,
        )

        store = get_ledger_store()
        repo = LedgerRepository(store=store)
        before_count = len(repo._records)
        repo.record_verified(
            "__verify_test__",
            "2099-01-01",
            "increase",
            "2099-01-01",
            100,
            105,
        )
        repo.save()

        repo2 = LedgerRepository(store=store)
        record = repo2.get_record("__verify_test__", "2099-01-01", "increase", "2099-01-01")
        if not record or record["price_after"] != 105:
            return CheckResult("Ledger read/write", False, "Wrote test record but could not read it back")

        # Remove test record
        key = record["key"]
        if key in repo2._records:
            del repo2._records[key]
        repo2.save()

        return CheckResult(
            "Ledger read/write",
            True,
            f"backend={store.backend_name}, existing_records={before_count}, roundtrip OK",
        )
    except Exception as e:
        return CheckResult("Ledger read/write", False, str(e))


def check_ledger_lock() -> CheckResult:
    try:
        from pricelabs_tool.ledger_store import LedgerRepository, get_ledger_store
        from pricelabs_tool.run_guard import AdjustmentRunInProgressError

        store = get_ledger_store()
        repo1 = LedgerRepository(store=store)
        repo1.acquire_lock("increase")

        repo2 = LedgerRepository(store=store)
        blocked = False
        try:
            repo2.acquire_lock("increase")
        except AdjustmentRunInProgressError:
            blocked = True

        repo1.release_lock()

        if not blocked:
            return CheckResult("Ledger distributed lock", False, "Second lock was not blocked")
        return CheckResult(
            "Ledger distributed lock",
            True,
            f"Lock acquire/block/release OK on {store.backend_name}",
        )
    except Exception as e:
        return CheckResult("Ledger distributed lock", False, str(e))


def check_slack() -> CheckResult:
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return CheckResult("Slack webhook", False, "SLACK_WEBHOOK_URL not set")

    import requests

    payload = {
        "blocks": [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":test_tube: *PriceLabs pipeline verification*\n"
                    "This is a test message from `verify_pipeline.py`. "
                    "If you see this, Slack reporting is configured correctly."
                ),
            },
        }]
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return CheckResult("Slack webhook", True, "Test message sent successfully")
    except Exception as e:
        return CheckResult("Slack webhook", False, str(e))


def print_results(results: List[CheckResult]) -> Tuple[int, int, int]:
    passed = 0
    failed = 0
    warned = 0
    print()
    print("=" * 60)
    print("PriceLabs Pipeline Verification")
    print("=" * 60)
    for r in results:
        icon = r.status_label
        print(f"\n[{icon}] {r.name}")
        if r.detail:
            for line in r.detail.split("\n"):
                print(f"      {line}")
        if r.passed:
            passed += 1
        elif r.required:
            failed += 1
        else:
            warned += 1
    print()
    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed, {warned} warnings")
    print("-" * 60)
    return passed, failed, warned


def run_live(direction: str) -> int:
    argv = [sys.executable, str(PROJECT_ROOT / "run_adjustment.py"), "--direction", direction]
    if not os.getenv("SLACK_WEBHOOK_URL"):
        argv.append("--no-slack")

    print(f"\n>>> Running LIVE adjustment: --direction {direction}")
    print(">>> This will write real price changes to PriceLabs.\n")
    proc = subprocess.run(argv, cwd=PROJECT_ROOT)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PriceLabs automation pipeline")
    parser.add_argument(
        "--test-slack",
        action="store_true",
        help="Send a test Slack message (requires SLACK_WEBHOOK_URL)",
    )
    parser.add_argument(
        "--test-ledger-lock",
        action="store_true",
        help="Also test distributed lock acquire/block/release on the ledger backend",
    )
    parser.add_argument(
        "--live",
        choices=["increase", "decrease"],
        help="Run a REAL adjustment after safe checks (writes to PriceLabs)",
    )
    parser.add_argument(
        "--skip-dry-run",
        action="store_true",
        help="Skip dry-run API previews (faster if API is slow)",
    )
    parser.add_argument(
        "--full-dry-run",
        action="store_true",
        help="Dry-run all configured listings (slow; default samples 8)",
    )
    args = parser.parse_args()
    sample_limit = 0 if args.full_dry_run else 8

    results: List[CheckResult] = []
    results.extend(check_env())
    results.append(check_unit_tests())

    # API-dependent checks
    api_result = check_pricelabs_api()
    results.append(api_result)

    if api_result.passed and not args.skip_dry_run:
        results.append(check_dry_run_preview("increase", sample_limit=sample_limit))
        results.append(check_dry_run_preview("decrease", sample_limit=sample_limit))

    results.append(check_ledger_read_write())
    if args.test_ledger_lock:
        results.append(check_ledger_lock())

    if args.test_slack:
        results.append(check_slack())

    passed, failed, warned = print_results(results)

    if failed > 0 and not args.live:
        print("\nFix required failures before creating automations.")
        return 1

    if warned > 0 and not args.live:
        print("\nWarnings are OK for local verification.")
        print("Set SLACK_WEBHOOK_URL and GITHUB_TOKEN in cloud automation secrets before go-live.")

    if args.live:
        if failed > 0:
            print("\nWarning: some checks failed but --live was requested.")
        live_code = run_live(args.live)
        if live_code != 0:
            return live_code
        print("\nLive run finished. Re-run without --live to confirm idempotency skips:")
        print(f"  python verify_pipeline.py   # dry-run should show 'would skip' for applied dates")
        return 0

    if failed == 0:
        print("\nPipeline checks OK. Recommended verification sequence:")
        print("  1. python verify_pipeline.py --test-ledger-lock")
        print("  2. python verify_pipeline.py --test-slack          # if webhook configured")
        print("  3. ADJUSTMENT_LEDGER_BACKEND=github GITHUB_TOKEN=... python verify_pipeline.py --test-ledger-lock")
        print("  4. python verify_pipeline.py --live increase       # one real write test")
        print("  5. python verify_pipeline.py                       # confirm idempotency skips")
        print("  6. Create morning/evening Cursor automations")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
