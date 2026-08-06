"""Run lock and adjustment ledger for idempotent price adjustments."""

import logging
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from pricelabs_tool.ledger_store import LedgerRepository, get_ledger_store

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = PROJECT_ROOT / "data" / "adjustment_runs"
LEDGER_FILE = LEDGER_DIR / "ledger.json"
LOCK_FILE = LEDGER_DIR / "run.lock"


class AdjustmentRunInProgressError(Exception):
    """Raised when another adjustment run holds the lock."""


def _direction_key(increase: bool) -> str:
    return "increase" if increase else "decrease"


def run_day_local() -> str:
    return date.today().isoformat()


class AdjustmentLedger:
    """Persistent record of verified adjustments per listing/date/direction/day."""

    def __init__(self, repository: Optional[LedgerRepository] = None):
        self._repo = repository or LedgerRepository(get_ledger_store())

    @property
    def backend_name(self) -> str:
        return self._repo.backend_name

    def get_record(
        self, listing_id: str, override_date: str, direction: str, run_day: str
    ) -> Optional[Dict]:
        return self._repo.get_record(listing_id, override_date, direction, run_day)

    def get_anchor(self, listing_id: str, override_date: str) -> Optional[Dict]:
        return self._repo.get_anchor(listing_id, override_date)

    def iter_verified_records(
        self,
        run_day: str,
        direction: Optional[str] = None,
        listing_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        return self._repo.iter_verified_records(
            run_day, direction=direction, listing_ids=listing_ids
        )

    def set_anchor(
        self,
        listing_id: str,
        override_date: str,
        reference_price: int,
        state: str,
    ) -> None:
        self._repo.set_anchor(listing_id, override_date, reference_price, state)

    def record_verified(
        self,
        listing_id: str,
        override_date: str,
        direction: str,
        run_day: str,
        price_before: int,
        price_after: int,
    ) -> None:
        self._repo.record_verified(
            listing_id,
            override_date,
            direction,
            run_day,
            price_before,
            price_after,
        )

    def save(self) -> None:
        self._repo.save()


def evaluate_date_action(
    listing_id: str,
    override_date: str,
    increase: bool,
    price_before: float,
    price_after: int,
    run_day: str,
    ledger: AdjustmentLedger,
) -> Tuple[str, Optional[str]]:
    """
    Decide whether to apply or skip an adjustment for one date.

    Returns:
        (action, reason) where action is "apply" or "skip"
    """
    direction = _direction_key(increase)
    current = int(price_before)
    record = ledger.get_record(listing_id, override_date, direction, run_day)

    if record and record.get("verified") and record.get("run_day") == run_day:
        expected_after = int(record["price_after"])
        if current == expected_after:
            return "skip", "Already adjusted and verified today for this direction"
        if current != price_after:
            return "apply", None

    if current == price_after:
        return "skip", "Price already at computed target (no change needed)"

    return "apply", None


def filter_adjustments_for_idempotency(
    listing_id: str,
    preview_rows: List[Dict],
    adjusted_overrides: List[Dict],
    increase: bool,
    run_day: str,
    ledger: AdjustmentLedger,
) -> Tuple[List[Dict], Dict]:
    """
    Filter overrides to apply based on ledger and current prices.

    Returns:
        (overrides_to_apply, stats dict with apply/skip counts)
    """
    preview_by_date = {row["date"]: row for row in preview_rows}
    stats = {
        "apply_count": 0,
        "skip_already_done": 0,
        "skip_no_change": 0,
    }
    to_apply: List[Dict] = []

    for override in adjusted_overrides:
        override_date = override["date"]
        row = preview_by_date.get(override_date)
        if not row:
            continue

        action, reason = evaluate_date_action(
            listing_id,
            override_date,
            increase,
            row["old_price"],
            int(override["price"]),
            run_day,
            ledger,
        )

        if action == "apply":
            stats["apply_count"] += 1
            to_apply.append(override)
        elif action == "skip":
            if reason and "Already adjusted" in reason:
                stats["skip_already_done"] += 1
            else:
                stats["skip_no_change"] += 1

    return to_apply, stats


@contextmanager
def adjustment_run_lock(increase: bool) -> Iterator[LedgerRepository]:
    """Prevent overlapping adjustment runs across local and cloud environments."""
    repo = LedgerRepository(get_ledger_store())
    direction = _direction_key(increase)
    logger.info("Acquiring adjustment run lock via %s", repo.backend_name)
    repo.acquire_lock(direction)
    try:
        yield repo
    finally:
        try:
            repo.release_lock()
            logger.info("Released adjustment run lock on %s", repo.backend_name)
        except Exception as e:
            logger.warning("Could not release adjustment run lock cleanly: %s", e)
