"""Tests for run failure descriptions."""

import json

from pricelabs_tool.ledger_store import LedgerPayloadError
from pricelabs_tool.run_errors import describe_run_failure
from pricelabs_tool.run_guard import AdjustmentRunInProgressError


def test_describe_lock_failure():
    exc = AdjustmentRunInProgressError("lock held since 2026-06-24")
    failure = describe_run_failure(exc)
    assert failure["error_type"] == "run_lock_held"
    assert "manifest.json" in failure["action"]


def test_describe_json_decode_failure():
    exc = json.JSONDecodeError("Expecting value", "", 0)
    failure = describe_run_failure(exc)
    assert failure["error_type"] == "ledger_json_decode"
    assert "migrate_ledger_shards.py" in failure["action"]


def test_describe_payload_failure():
    exc = LedgerPayloadError("GitHub file 'ledger.json' is 7,611,507 bytes")
    failure = describe_run_failure(exc)
    assert failure["error_type"] == "ledger_payload"
    assert "migrate_ledger_shards.py" in failure["action"]
