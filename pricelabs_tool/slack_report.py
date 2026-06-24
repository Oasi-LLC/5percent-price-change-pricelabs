"""Format and send PriceLabs adjustment run reports to Slack."""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests


def _direction_label(increase: bool) -> str:
    return "Increase (+5%)" if increase else "Decrease (-5%)"


def _status_emoji(summary: Dict) -> str:
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

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": overview}},
    ]

    failed = summary["failed_listings"]
    if failed:
        lines = []
        for item in failed[:15]:
            prefix = ""
            if item.get("double_adjustment_blocked"):
                prefix = "[DOUBLE ADJUSTMENT] "
            elif item.get("verification_failed"):
                prefix = "[VERIFY FAILED] "
            lines.append(
                f"• *{item['name']}* (`{item['id']}`): "
                f"{prefix}{item.get('message', 'Unknown error')}"
            )
        if len(failed) > 15:
            lines.append(f"_…and {len(failed) - 15} more_")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Failed listings*\n" + "\n".join(lines)},
        })

    skipped_no_work = [
        r for r in summary["skipped_listings"]
        if "Auto-skipped child" not in r.get("message", "")
    ]
    if skipped_no_work:
        lines = []
        for item in skipped_no_work[:10]:
            lines.append(f"• *{item['name']}*: {item.get('message', 'Skipped')}")
        if len(skipped_no_work) > 10:
            lines.append(f"_…and {len(skipped_no_work) - 10} more_")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Skipped (no qualifying overrides)*\n" + "\n".join(lines)},
        })

    # Success highlights: listings with most dates updated
    successful = sorted(
        summary["successful_listings"],
        key=lambda r: r.get("dates_updated", 0),
        reverse=True,
    )
    if successful:
        lines = []
        for item in successful[:8]:
            batna_note = ""
            if item.get("batna_clamped_count"):
                batna_note = f" ({item['batna_clamped_count']} BATNA)"
            lines.append(
                f"• *{item['name']}*: {item.get('dates_updated', 0)} date(s){batna_note}"
            )
        remaining = len(successful) - 8
        if remaining > 0:
            lines.append(f"_…and {remaining} more successful listing(s)_")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Updated listings*\n" + "\n".join(lines)},
        })

    return {"blocks": blocks}


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
