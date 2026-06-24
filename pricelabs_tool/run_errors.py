"""Human-readable run failure descriptions for logs and Slack."""

import json
from typing import Any, Dict, Optional

from pricelabs_tool.ledger_store import LedgerPayloadError, LedgerResponseError
from pricelabs_tool.run_guard import AdjustmentRunInProgressError

GITHUB_CONTENTS_API_LIMIT_BYTES = 1_000_000


def describe_run_failure(exc: BaseException) -> Dict[str, str]:
    """Return structured fields for logs and Slack when a run fails."""
    if isinstance(exc, AdjustmentRunInProgressError):
        return {
            "error_type": "run_lock_held",
            "title": "Ledger run lock is already held",
            "detail": str(exc),
            "action": (
                "Wait for the other run to finish, or clear `\"lock\": null` in "
                "`data/adjustment_runs/manifest.json` on branch `automation-state` "
                "after confirming no active run."
            ),
        }

    if isinstance(exc, LedgerPayloadError):
        return {
            "error_type": "ledger_payload",
            "title": "GitHub ledger file cannot be read",
            "detail": str(exc),
            "action": (
                "If the legacy ledger grew past GitHub's 1 MB API limit, run "
                "`python3 migrate_ledger_shards.py /path/to/ledger.json --clear-lock` "
                "locally with GITHUB_TOKEN set, then retry the automation."
            ),
        }

    if isinstance(exc, LedgerResponseError):
        return {
            "error_type": "ledger_api_response",
            "title": "GitHub ledger API returned an invalid response",
            "detail": str(exc),
            "action": (
                "Retry in a few minutes. If it persists, verify GITHUB_TOKEN access "
                "to `automation-state` and check GitHub API status/rate limits."
            ),
        }

    if isinstance(exc, PermissionError):
        return {
            "error_type": "github_permission",
            "title": "GitHub token permission error",
            "detail": str(exc),
            "action": (
                "Confirm the fine-grained PAT is approved for Oasi-LLC and has "
                "Contents read/write on the repo."
            ),
        }

    if isinstance(exc, json.JSONDecodeError):
        return {
            "error_type": "ledger_json_decode",
            "title": "Could not parse ledger JSON from GitHub",
            "detail": str(exc),
            "action": (
                "This usually means GitHub returned an empty body or the legacy "
                f"`ledger.json` exceeded the {GITHUB_CONTENTS_API_LIMIT_BYTES // 1_000_000} MB "
                "Contents API read limit. Migrate with `migrate_ledger_shards.py`, "
                "clear the lock, and retry."
            ),
        }

    return {
        "error_type": type(exc).__name__,
        "title": "Adjustment run failed before or during processing",
        "detail": str(exc) or repr(exc),
        "action": "Check the automation logs for the full traceback.",
    }


def apply_failure_to_summary(summary: Dict[str, Any], failure: Dict[str, str]) -> None:
    summary["run_error"] = failure.get("detail", "")
    summary["run_error_type"] = failure.get("error_type", "")
    summary["run_error_title"] = failure.get("title", "")
    summary["run_error_action"] = failure.get("action", "")
