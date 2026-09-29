"""Tests for reference-price toggle semantics and BATNA floor enforcement."""

from pricelabs_tool.reference_price import (
    clamp_price_to_batna,
    compute_target_price,
    resolve_adjustment_for_date,
    resolve_reference,
)


def test_clamp_price_to_batna():
    assert clamp_price_to_batna(166, 199.0) == (199, True)
    assert clamp_price_to_batna(250, 199.0) == (250, False)
    assert clamp_price_to_batna(166, None) == (166, False)


def test_restore_after_decrease_clamps_to_batna():
    """Restore must not push below BATNA when old reference is under the floor."""
    target, clamped, action = compute_target_price(
        increase=True,
        reference=166,
        state="decreased",
        batna_floor=199.0,
    )
    assert action == "restore_reference_after_decrease"
    assert target == 199
    assert clamped is True


def test_restore_after_increase_clamps_to_batna():
    target, clamped, action = compute_target_price(
        increase=False,
        reference=166,
        state="increased",
        batna_floor=199.0,
    )
    assert action == "restore_reference_after_increase"
    assert target == 199
    assert clamped is True


def test_stale_anchor_below_batna_is_refreshed():
    """Raised BATNA invalidates anchors below the new floor (Malvern Loft)."""
    reference, state, refreshed = resolve_reference(
        live_price=199,
        stored_reference=166,
        batna_floor=199.0,
    )
    assert refreshed is True
    assert state == "neutral"
    assert reference == 199


def test_malvern_loft_increase_does_not_restore_below_floor():
    """
    Regression: live at BATNA-clamped decreased tier, stale ref 166, floor 199.
    Increase must not write 166 back to PriceLabs.
    """
    resolved = resolve_adjustment_for_date(
        live_price=199,
        stored_reference=166,
        increase=True,
        batna_floor=199.0,
    )
    assert resolved["new_price"] >= 199
    assert resolved["reference_refreshed"] is True
    assert resolved["reference_price"] == 199
    # Neutral after refresh → apply +5% from new floor
    assert resolved["new_price"] == 208
    assert resolved["action"] == "apply_increase_from_reference"


def test_normal_restore_unchanged_when_reference_above_batna():
    resolved = resolve_adjustment_for_date(
        live_price=190,
        stored_reference=200,
        increase=True,
        batna_floor=189.0,
    )
    assert resolved["inferred_state"] == "decreased"
    assert resolved["new_price"] == 200
    assert resolved["clamped"] is False
    assert resolved["action"] == "restore_reference_after_decrease"
