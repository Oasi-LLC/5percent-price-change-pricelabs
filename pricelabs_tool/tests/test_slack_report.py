"""Tests for Slack report formatting."""

from pricelabs_tool.slack_report import (
    _aggregate_by_property,
    _format_property_line,
    format_slack_message,
)


def test_aggregate_by_property_rolls_up_all_listings():
    results = [
        {"id": "146908", "status": "error", "double_adjustment_blocked": True},
        {"id": "146944", "status": "error", "double_adjustment_blocked": True},
        {"id": "146946", "status": "error", "double_adjustment_blocked": True},
        {"id": "260001", "status": "skipped"},
        {"id": "203812___362535", "status": "skipped"},
        {"id": "203812___364773", "status": "success", "dates_updated": 1},
    ]
    rows = _aggregate_by_property(results)
    by_name = {row["prop_name"]: row for row in rows}
    assert by_name["FLOHOM"] == {
        "prop_key": "flo1",
        "prop_name": "FLOHOM",
        "listings": 4,
        "successful": 0,
        "failed": 3,
        "skipped": 1,
        "dates_updated": 0,
        "double_blocked": 3,
        "verification_failed": 0,
    }
    assert by_name["Onera"]["listings"] == 2
    assert by_name["Onera"]["dates_updated"] == 1


def test_format_property_line_shows_full_breakdown():
    line = _format_property_line({
        "prop_name": "FLOHOM",
        "listings": 17,
        "successful": 0,
        "skipped": 14,
        "failed": 3,
        "dates_updated": 0,
        "double_blocked": 3,
        "verification_failed": 0,
    })
    assert "17 listings" in line
    assert "0 updated" in line
    assert "14 skipped" in line
    assert "3 failed" in line
    assert "double adjustment" in line


def test_format_slack_message_is_property_level_only():
    summary = {
        "total": 90,
        "successful": 1,
        "failed": 3,
        "skipped": 86,
        "dates_updated": 1,
        "batna_clamped": 0,
        "failed_listings": [{"name": "FLOHOM 01", "id": "146908"}],
        "skipped_listings": [{"name": "Cocoon"}],
        "successful_listings": [],
    }
    results = [
        {"id": "146908", "name": "FLOHOM 01", "status": "error", "double_adjustment_blocked": True},
        {"id": "203812___362535", "name": "Cocoon", "status": "skipped"},
    ]
    payload = format_slack_message(True, summary, results)
    block_text = " ".join(
        block["text"]["text"]
        for block in payload["blocks"]
        if block.get("type") == "section"
    )
    assert "*Property summary*" in block_text
    assert "Failed listings" not in block_text
    assert "FLOHOM 01" not in block_text
    assert "text" in payload
