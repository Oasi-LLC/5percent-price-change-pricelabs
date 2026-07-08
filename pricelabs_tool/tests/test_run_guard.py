"""Tests for adjustment idempotency and run guard logic."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pricelabs_tool.ledger_store import (
    FileLedgerStore,
    GitHubLedgerStore,
    LedgerRepository,
    LedgerResponseError,
    empty_manifest,
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


def test_reapply_increase_when_live_price_above_verified_target():
    ledger = _ledger_with_record("123", "2026-06-01", "increase", "2026-06-24", 100, 105)
    action, reason = evaluate_date_action(
        "123", "2026-06-01", True, 110, 115, "2026-06-24", ledger
    )
    assert action == "apply"
    assert reason is None


def test_reapply_decrease_when_live_price_below_verified_target():
    ledger = _ledger_with_record("123", "2026-06-01", "decrease", "2026-06-24", 200, 190)
    action, reason = evaluate_date_action(
        "123", "2026-06-01", False, 180, 171, "2026-06-24", ledger
    )
    assert action == "apply"
    assert reason is None


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


def test_filter_reapplies_when_live_price_changed_since_verified_run():
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
        assert len(to_apply) == 1
        assert to_apply[0]["price"] == "115"
        assert stats["apply_count"] == 1


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
    manifest = empty_manifest()
    shard_records = [{
        "key": "a|b|increase|2026-06-24",
        "listing_id": "a",
        "date": "b",
        "direction": "increase",
        "run_day": "2026-06-24",
        "price_before": 100,
        "price_after": 105,
        "verified": True,
    }]
    manifest_encoded = json.dumps(manifest).encode()
    shard_encoded = json.dumps({"listing_id": "a", "records": shard_records}).encode()

    def _mock_get(url, headers=None, params=None, timeout=30):
        response = MagicMock()
        response.status_code = 200
        if url.endswith("/git/ref/heads/automation-state"):
            response.text = '{"object":{"sha":"branchsha"}}'
            response.json.return_value = {"object": {"sha": "branchsha"}}
            return response
        if "manifest.json" in url:
            response.text = '{"content":"' + __import__("base64").b64encode(manifest_encoded).decode() + '","sha":"manifestsha","size":123}'
            response.json.return_value = {
                "content": __import__("base64").b64encode(manifest_encoded).decode(),
                "sha": "manifestsha",
                "size": 123,
            }
            return response
        if "/records/a.json" in url:
            response.text = '{"content":"' + __import__("base64").b64encode(shard_encoded).decode() + '","sha":"shardsha","size":456}'
            response.json.return_value = {
                "content": __import__("base64").b64encode(shard_encoded).decode(),
                "sha": "shardsha",
                "size": 456,
            }
            return response
        response.status_code = 404
        response.text = ""
        response.json.side_effect = ValueError("404")
        return response

    put_response = MagicMock()
    put_response.status_code = 200
    put_response.raise_for_status = MagicMock()

    with patch("pricelabs_tool.ledger_store.requests.get", side_effect=_mock_get):
        with patch("pricelabs_tool.ledger_store.requests.put", return_value=put_response) as put:
            store = GitHubLedgerStore(
                repo="Oasi-LLC/5percent-price-change-pricelabs",
                token="test-token",
            )
            store._ref_ensured = True
            loaded_manifest, sha = store.read_manifest()
            assert sha == "manifestsha"
            records, shard_sha = store.read_listing_shard("a")
            assert records[0]["price_after"] == 105
            store.write_manifest(loaded_manifest, sha)
            store.write_listing_shard("a", records, shard_sha)
            assert put.call_count == 2


def test_github_store_large_file_raises_payload_error():
    from pricelabs_tool.ledger_store import LedgerPayloadError, _decode_github_file_content

    with pytest.raises(LedgerPayloadError) as exc:
        _decode_github_file_content({"size": 2_000_000, "content": ""}, "ledger.json")
    assert "1 MB" in str(exc.value)


def test_github_store_reads_large_shard_via_raw_api():
    from pricelabs_tool.ledger_store import GitHubLedgerStore

    shard_payload = {
        "listing_id": "big",
        "records": [{"key": "big|2026-06-01|increase|2026-06-29", "verified": True}],
    }
    raw_text = json.dumps(shard_payload)

    metadata_response = MagicMock()
    metadata_response.status_code = 200
    metadata_response.text = json.dumps(
        {
            "content": "",
            "sha": "bigsha",
            "size": 1_500_000,
        }
    )
    metadata_response.json.return_value = json.loads(metadata_response.text)

    raw_response = MagicMock()
    raw_response.status_code = 200
    raw_response.text = raw_text
    raw_response.raise_for_status = MagicMock()

    def _mock_get(url, headers=None, params=None, timeout=None):
        if headers and headers.get("Accept") == "application/vnd.github.raw+json":
            return raw_response
        return metadata_response

    with patch("pricelabs_tool.ledger_store.requests.get", side_effect=_mock_get):
        store = GitHubLedgerStore(
            repo="Oasi-LLC/5percent-price-change-pricelabs",
            token="test-token",
        )
        store._ref_ensured = True
        records, shard_sha = store.read_listing_shard("big")
        assert shard_sha == "bigsha"
        assert records[0]["key"].startswith("big|")


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
