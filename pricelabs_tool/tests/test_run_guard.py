"""Tests for adjustment idempotency and run guard logic."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from pricelabs_tool.ledger_store import (
    FileLedgerStore,
    GitHubLedgerStore,
    LedgerRepository,
    LedgerResponseError,
    empty_payload,
    resolve_ledger_backend,
)
from pricelabs_tool.run_guard import (
    AdjustmentLedger,
    AdjustmentRunInProgressError,
    evaluate_date_action,
    filter_adjustments_for_idempotency,
)


def _ledger_with_record(
    listing_id: str,
    override_date: str,
    direction: str,
    run_day: str,
    price_before: int,
    price_after: int,
) -> AdjustmentLedger:
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        repo = LedgerRepository(store=store)
        ledger = AdjustmentLedger(repository=repo)
        ledger.record_verified(
            listing_id, override_date, direction, run_day, price_before, price_after
        )
        ledger.save()
        reloaded = AdjustmentLedger(repository=LedgerRepository(store=store))
        return reloaded


def test_skip_when_already_verified_today():
    ledger = _ledger_with_record("123", "2026-06-01", "increase", "2026-06-24", 100, 105)
    action, reason = evaluate_date_action(
        "123", "2026-06-01", True, 105, 110, "2026-06-24", ledger
    )
    assert action == "skip"
    assert "Already adjusted" in reason


def test_block_double_increase():
    ledger = _ledger_with_record("123", "2026-06-01", "increase", "2026-06-24", 100, 105)
    action, reason = evaluate_date_action(
        "123", "2026-06-01", True, 110, 115, "2026-06-24", ledger
    )
    assert action == "block"
    assert "Double adjustment" in reason


def test_block_double_decrease():
    ledger = _ledger_with_record("123", "2026-06-01", "decrease", "2026-06-24", 200, 190)
    action, reason = evaluate_date_action(
        "123", "2026-06-01", False, 180, 171, "2026-06-24", ledger
    )
    assert action == "block"
    assert "Double adjustment" in reason


def test_apply_when_no_prior_record():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        ledger = AdjustmentLedger(repository=LedgerRepository(store=store))
        action, reason = evaluate_date_action(
            "123", "2026-06-01", True, 100, 105, "2026-06-24", ledger
        )
        assert action == "apply"
        assert reason is None


def test_skip_when_price_already_at_target():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        ledger = AdjustmentLedger(repository=LedgerRepository(store=store))
        action, reason = evaluate_date_action(
            "123", "2026-06-01", True, 105, 105, "2026-06-24", ledger
        )
        assert action == "skip"
        assert "no change" in reason.lower()


def test_filter_blocks_listing_with_double_adjustment():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        repo = LedgerRepository(store=store)
        ledger = AdjustmentLedger(repository=repo)
        ledger.record_verified("123", "2026-06-01", "increase", "2026-06-24", 100, 105)
        preview_rows = [{"date": "2026-06-01", "old_price": 110, "clamped": False}]
        adjusted = [{
            "date": "2026-06-01",
            "price": "115",
            "price_type": "fixed",
            "currency": "USD",
            "min_stay": 1,
        }]
        to_apply, stats = filter_adjustments_for_idempotency(
            "123", preview_rows, adjusted, True, "2026-06-24", ledger
        )
        assert to_apply == []
        assert stats["blocked"] == 1


def test_evening_decrease_allowed_after_morning_increase():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        ledger = AdjustmentLedger(repository=LedgerRepository(store=store))
        ledger.record_verified("123", "2026-06-01", "increase", "2026-06-24", 100, 105)
        action, _ = evaluate_date_action(
            "123", "2026-06-01", False, 105, 99, "2026-06-24", ledger
        )
        assert action == "apply"


def test_file_ledger_persists_across_repositories():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.json"
        store = FileLedgerStore(path=path)
        repo1 = LedgerRepository(store=store)
        ledger1 = AdjustmentLedger(repository=repo1)
        ledger1.record_verified("123", "2026-06-01", "increase", "2026-06-24", 100, 105)
        ledger1.save()

        repo2 = LedgerRepository(store=store)
        ledger2 = AdjustmentLedger(repository=repo2)
        record = ledger2.get_record("123", "2026-06-01", "increase", "2026-06-24")
        assert record["price_after"] == 105


def test_distributed_lock_blocks_second_run():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        repo1 = LedgerRepository(store=store)
        repo1.acquire_lock("increase")

        repo2 = LedgerRepository(store=store)
        try:
            repo2.acquire_lock("increase")
            raised = False
        except AdjustmentRunInProgressError:
            raised = True
        assert raised is True
        repo1.release_lock()


def test_resolve_ledger_backend_prefers_github_when_token_set():
    with patch.dict(
        "os.environ",
        {"ADJUSTMENT_LEDGER_BACKEND": "auto", "GITHUB_TOKEN": "test-token"},
        clear=False,
    ):
        assert resolve_ledger_backend() == "github"


def test_github_store_read_write_roundtrip():
    payload = empty_payload()
    payload["records"] = [{
        "key": "a|b|increase|2026-06-24",
        "listing_id": "a",
        "date": "b",
        "direction": "increase",
        "run_day": "2026-06-24",
        "price_before": 100,
        "price_after": 105,
        "verified": True,
    }]
    encoded = json.dumps(payload).encode()

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.json.return_value = {
        "content": __import__("base64").b64encode(encoded).decode(),
        "sha": "abc123",
    }

    put_response = MagicMock()
    put_response.status_code = 200
    put_response.raise_for_status = MagicMock()

    ref_exists = MagicMock()
    ref_exists.status_code = 200

    with patch("pricelabs_tool.ledger_store.requests.get", return_value=get_response):
        with patch("pricelabs_tool.ledger_store.requests.put", return_value=put_response) as put:
            store = GitHubLedgerStore(
                repo="Oasi-LLC/5percent-price-change-pricelabs",
                token="test-token",
            )
            store._ref_ensured = True
            loaded, sha = store.read()
            assert sha == "abc123"
            assert loaded["records"][0]["price_after"] == 105
            store.write(loaded, sha)
            put.assert_called_once()


def test_github_store_empty_response_raises_ledger_response_error():
    empty_response = MagicMock()
    empty_response.status_code = 200
    empty_response.text = ""
    empty_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)

    with patch("pricelabs_tool.ledger_store.requests.get", return_value=empty_response):
        store = GitHubLedgerStore(
            repo="Oasi-LLC/5percent-price-change-pricelabs",
            token="test-token",
        )
        store._ref_ensured = True
        try:
            store.read()
            assert False, "expected LedgerResponseError"
        except LedgerResponseError as e:
            assert "Empty response body" in str(e)


def test_release_lock_survives_reload_failure():
    with tempfile.TemporaryDirectory() as tmp:
        store = FileLedgerStore(path=Path(tmp) / "ledger.json")
        repo = LedgerRepository(store=store)
        repo.acquire_lock("increase")
        assert repo._run_id is not None

        with patch.object(repo, "reload", side_effect=LedgerResponseError("bad json")):
            repo.release_lock()

        assert repo._run_id is None
