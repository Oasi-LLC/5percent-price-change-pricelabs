"""Format and send PriceLabs adjustment run reports to Slack."""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from pricelabs_tool.property_config import listing_to_property, load_property_config


def _direction_label(increase: bool) -> str:
    return "Increase (+5%)" if increase else "Decrease (-5%)"


_SLACK_TEXT_LIMIT = 2800
_PROPERTIES_PER_BLOCK = 12


def _aggregate_by_property(results: List[Dict]) -> List[Dict]:
    """Roll listing results up to property groups from properties_config.yaml."""
    prop_config = load_property_config()
    by_key: Dict[str, Dict] = {}

    for result in results:
        prop_key, prop_name = listing_to_property(str(result.get("id")), prop_config)
        if prop_key not in by_key:
            by_key[prop_key] = {
                "prop_key": prop_key,
                "prop_name": prop_name,
                "listings": 0,
                "successful": 0,
                "failed": 0,
                "skipped": 0,
                "dates_updated": 0,
                "double_blocked": 0,
                "verification_failed": 0,
            }
        stats = by_key[prop_key]
        stats["listings"] += 1
        status = result.get("status")
        if status == "success":
            stats["successful"] += 1
            stats["dates_updated"] += int(result.get("dates_updated", 0) or 0)
        elif status == "error":
            stats["failed"] += 1
            if result.get("double_adjustment_blocked"):
                stats["double_blocked"] += 1
            if result.get("verification_failed"):
                stats["verification_failed"] += 1
        elif status == "skipped":
            stats["skipped"] += 1

    def sort_key(item: Dict) -> Tuple[int, int, str]:
        # Failed properties first, then those with updates, then alphabetical.
        return (
            -item["failed"],
            -item["dates_updated"],
            item["prop_name"].lower(),
        )

    return sorted(by_key.values(), key=sort_key)


def _format_property_line(stats: Dict) -> str:
    """One line per property — full listing accounting, no per-date detail."""
    name = stats["prop_name"]
    n = stats["listings"]
    updated = stats["successful"]
    skipped = stats["skipped"]
    failed = stats["failed"]
    dates = stats["dates_updated"]

    updated_part = f"{updated} updated"
    if dates:
        updated_part += f" ({dates} date{'s' if dates != 1 else ''})"

    line = (
        f"• *{name}* — {n} listing{'s' if n != 1 else ''} · "
        f"{updated_part} · {skipped} skipped · {failed} failed"
    )
    if failed:
        if stats["double_blocked"]:
            line += " _(double adjustment)_"
        elif stats["verification_failed"]:
            line += " _(verify failed)_"
    return line


def _build_property_summary_blocks(results: List[Dict]) -> List[Dict]:
    """Property-level rollup for every processed listing."""
    rows = _aggregate_by_property(results)
    if not rows:
        return []

    lines = [_format_property_line(row) for row in rows]
    blocks: List[Dict] = []
    for i in range(0, len(lines), _PROPERTIES_PER_BLOCK):
        chunk = lines[i : i + _PROPERTIES_PER_BLOCK]
        header = "*Property summary*" if i == 0 else "*Property summary (continued)*"
        text = header + "\n" + "\n".join(chunk)
        if len(text) > _SLACK_TEXT_LIMIT:
            text = text[: _SLACK_TEXT_LIMIT - 1] + "…"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        })
    return blocks


def _status_emoji(summary: Dict) -> str:
    if summary.get("run_error"):
        return ":warning:"
    if summary.get("double_adjustment_blocked", 0) > 0:
        return ":rotating_light:"
    if summary["failed"] > 0:
        return ":x:"
    if summary["successful"] == 0 and summary["skipped"] == summary["total"]:
        return ":warning:"
    return ":white_check_mark:"


def format_slack_message(
    increase: bool,
    summary: Dict,
    results: List[Dict],
) -> Dict:
    """Build a Slack incoming-webhook payload with run summary and details."""
    direction = _direction_label(increase)
    emoji = _status_emoji(summary)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if summary.get("run_error"):
        header = f"{emoji} *PriceLabs adjustment run ended with errors* — {direction}"
    else:
        header = f"{emoji} *PriceLabs adjustment complete* — {direction}"
    overview = (
        f"*Run at:* {timestamp}\n"
        f"*Listings processed:* {summary['total']}\n"
        f"*Successful:* {summary['successful']}  |  "
        f"*Failed:* {summary['failed']}  |  "
        f"*Skipped:* {summary['skipped']}\n"
        f"*Dates updated:* {summary['dates_updated']}"
    )
    if summary["batna_clamped"]:
        overview += f"  |  *BATNA floor applied:* {summary['batna_clamped']} date(s)"
    if summary.get("dates_verified"):
        overview += f"\n*Verified against pre-adjustment rates:* {summary['dates_verified']} date(s)"
    if summary.get("skipped_booked"):
        overview += f"\n*Skipped (booked dates):* {summary['skipped_booked']} date(s)"
    if summary.get("already_adjusted"):
        overview += f"\n*Skipped (already at target):* {summary['already_adjusted']} date(s)"
    if summary.get("double_adjustment_blocked"):
        overview += (
            f"\n:rotating_light: *Double-adjustment blocked:* "
            f"{summary['double_adjustment_blocked']} listing(s)"
        )
    if summary.get("verification_failed"):
        overview += (
            f"\n:x: *Verification failed:* {summary['verification_failed']} listing(s)"
        )
    if summary.get("ledger_backend"):
        overview += f"\n*Idempotency ledger:* `{summary['ledger_backend']}`"
    if summary.get("run_error"):
        overview += f"\n:warning: *Run error:* {summary['run_error']}"
    if summary.get("run_error_title"):
        overview += f"\n*Failure:* {summary['run_error_title']}"
    if summary.get("run_error_action"):
        overview += f"\n*What to do:* {summary['run_error_action']}"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": overview}},
    ]
    blocks.extend(_build_property_summary_blocks(results))

    if summary.get("run_error") and summary.get("total", 0) == 0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*No listings were processed.* The run failed while reading or "
                    "locking the idempotency ledger before PriceLabs updates began."
                ),
            },
        })

    fallback = (
        f"PriceLabs {_direction_label(increase)}: "
        f"{summary['successful']} ok, {summary['failed']} failed, "
        f"{summary['skipped']} skipped, {summary['dates_updated']} dates updated"
    )
    return {"text": fallback, "blocks": blocks}


def send_slack_report(
    increase: bool,
    summary: Dict,
    results: List[Dict],
    webhook_url: Optional[str] = None,
) -> bool:
    """
    Post run summary to Slack via incoming webhook.

    Returns True if sent successfully, False if skipped or failed.
    """
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return False

    payload = format_slack_message(increase, summary, results)
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return True
