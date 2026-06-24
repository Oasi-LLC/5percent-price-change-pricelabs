#!/usr/bin/env python3
"""
Headless PriceLabs ±5% adjustment runner for automation pipelines.

Usage:
    python run_adjustment.py --direction increase
    python run_adjustment.py --direction decrease

Environment:
    PRICELABS_API_KEY   (required)
    API_BASE_URL        (optional)
    SLACK_WEBHOOK_URL   (optional — posts run summary when set)

Cloud idempotency (recommended for Cursor cloud agents):
    GITHUB_TOKEN                    (required for shared ledger across runs)
    ADJUSTMENT_LEDGER_BACKEND       (optional: auto | file | github; default auto)
    ADJUSTMENT_LEDGER_GITHUB_REPO   (optional; default Oasi-LLC/5percent-price-change-pricelabs)
    ADJUSTMENT_LEDGER_GITHUB_REF    (optional; default automation-state)
    ADJUSTMENT_LEDGER_GITHUB_PATH   (optional; default data/adjustment_runs/manifest.json)
"""

import argparse
import logging
import sys
from typing import Dict, List, Optional

from dotenv import load_dotenv

from pricelabs_tool.batch_runner import (
    AdjustmentRunInProgressError,
    batch_update,
    fetch_configured_listings,
    summarize_results,
)
from pricelabs_tool.ledger_store import get_ledger_store, resolve_ledger_backend
from pricelabs_tool.run_errors import apply_failure_to_summary, describe_run_failure
from pricelabs_tool.slack_report import send_slack_report

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PriceLabs ±5% fixed-override adjustments for all configured listings."
    )
    parser.add_argument(
        "--direction",
        required=True,
        choices=["increase", "decrease"],
        help="Adjustment direction: increase (+5%%) or decrease (-5%%)",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="Skip Slack notification even if SLACK_WEBHOOK_URL is set",
    )
    parser.add_argument(
        "--max-listings",
        type=int,
        default=0,
        help="Process only the first N configured listings (0 = all). Useful for verification runs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    increase = args.direction == "increase"

    logger.info("Starting PriceLabs adjustment run (direction=%s)", args.direction)
    logger.info("Ledger backend mode: %s", resolve_ledger_backend())

    listings, excluded_count = fetch_configured_listings()
    logger.info(
        "Loaded %s configured listing(s) (%s excluded as not in properties_config.yaml)",
        len(listings),
        excluded_count,
    )

    if not listings:
        logger.error("No configured listings to process. Check API key and properties_config.yaml.")
        return 1

    if args.max_listings and args.max_listings > 0:
        listings = listings[: args.max_listings]
        logger.info("Limited to first %s listing(s) for this run", len(listings))

    results: List[Dict] = []
    run_error: Optional[str] = None
    failure_info: Optional[Dict[str, str]] = None
    try:
        results = batch_update(listings, increase=increase)
    except AdjustmentRunInProgressError as e:
        logger.error(str(e))
        failure_info = describe_run_failure(e)
        run_error = failure_info["detail"]
    except Exception as e:
        logger.exception("Batch update failed: %s", e)
        failure_info = describe_run_failure(e)
        run_error = failure_info["detail"]

    summary = summarize_results(results)
    summary["ledger_backend"] = get_ledger_store().backend_name
    if failure_info:
        apply_failure_to_summary(summary, failure_info)

    logger.info(
        "Run complete: %s successful, %s failed, %s skipped, %s dates updated",
        summary["successful"],
        summary["failed"],
        summary["skipped"],
        summary["dates_updated"],
    )
    if run_error:
        logger.error(
            "Run ended with error after processing %s listing(s): %s — %s",
            len(results),
            summary.get("run_error_title", "failure"),
            run_error,
        )
        if summary.get("run_error_action"):
            logger.error("Suggested action: %s", summary["run_error_action"])

    if not args.no_slack:
        try:
            if send_slack_report(increase, summary, results):
                logger.info("Slack report sent")
            else:
                logger.warning("SLACK_WEBHOOK_URL not set; skipping Slack notification")
        except Exception as e:
            logger.error("Failed to send Slack report: %s", e)

    if run_error:
        return 1

    if summary["failed"] > 0:
        for item in summary["failed_listings"]:
            logger.error("Failed: %s (%s) — %s", item["name"], item["id"], item.get("message"))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
