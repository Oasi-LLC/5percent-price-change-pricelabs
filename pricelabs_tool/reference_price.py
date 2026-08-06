"""Reference-price anchor and toggle semantics for ±5% adjustments."""

from typing import Any, Dict, Literal, Optional, Tuple

from pricelabs_tool.batna import apply_adjustment_with_batna

AdjustmentState = Literal["neutral", "decreased", "increased", "manual"]
DEFAULT_TOLERANCE = 2
DEFAULT_ADJUSTMENT_PERCENTAGE = 5


def price_matches(actual: int, expected: int, tolerance: int = DEFAULT_TOLERANCE) -> bool:
    return abs(actual - expected) <= tolerance


def tier_targets(
    reference: int,
    batna_floor: Optional[float],
    adjustment_percentage: float = DEFAULT_ADJUSTMENT_PERCENTAGE,
) -> Tuple[int, int]:
    """Return (decreased_target, increased_target) from reference price."""
    decreased, _ = apply_adjustment_with_batna(
        float(reference),
        increase=False,
        batna_floor=batna_floor,
        adjustment_percentage=adjustment_percentage,
    )
    increased, _ = apply_adjustment_with_batna(
        float(reference),
        increase=True,
        batna_floor=batna_floor,
        adjustment_percentage=adjustment_percentage,
    )
    return decreased, increased


def infer_state(
    live_price: int,
    reference: int,
    decreased_target: int,
    increased_target: int,
    tolerance: int = DEFAULT_TOLERANCE,
) -> AdjustmentState:
    if price_matches(live_price, reference, tolerance):
        return "neutral"
    if price_matches(live_price, decreased_target, tolerance):
        return "decreased"
    if price_matches(live_price, increased_target, tolerance):
        return "increased"
    return "manual"


def resolve_reference(
    live_price: int,
    stored_reference: Optional[int],
    batna_floor: Optional[float],
    adjustment_percentage: float = DEFAULT_ADJUSTMENT_PERCENTAGE,
    tolerance: int = DEFAULT_TOLERANCE,
) -> Tuple[int, AdjustmentState, bool]:
    """
    Resolve active reference and inferred state from live price.

    Returns:
        (reference, state, reference_was_refreshed)
    """
    live = int(live_price)
    if stored_reference is None:
        return live, "neutral", True

    reference = int(stored_reference)
    decreased, increased = tier_targets(reference, batna_floor, adjustment_percentage)
    state = infer_state(live, reference, decreased, increased, tolerance)
    if state == "manual":
        return live, "neutral", True
    return reference, state, False


def compute_target_price(
    increase: bool,
    reference: int,
    state: AdjustmentState,
    batna_floor: Optional[float],
    adjustment_percentage: float = DEFAULT_ADJUSTMENT_PERCENTAGE,
) -> Tuple[int, bool, str]:
    """
    Compute override target from reference anchor and toggle rules.

    Returns:
        (target_price, batna_clamped, action_label)
    """
    decreased, increased = tier_targets(reference, batna_floor, adjustment_percentage)

    if increase:
        if state == "decreased":
            return reference, False, "restore_reference_after_decrease"
        if state == "increased":
            return increased, False, "apply_increase_from_reference"
        target, clamped = apply_adjustment_with_batna(
            float(reference),
            increase=True,
            batna_floor=batna_floor,
            adjustment_percentage=adjustment_percentage,
        )
        return target, clamped, "apply_increase_from_reference"

    if state == "increased":
        return reference, False, "restore_reference_after_increase"
    if state == "decreased":
        target, clamped = apply_adjustment_with_batna(
            float(reference),
            increase=False,
            batna_floor=batna_floor,
            adjustment_percentage=adjustment_percentage,
        )
        return target, clamped, "apply_decrease_from_reference"
    target, clamped = apply_adjustment_with_batna(
        float(reference),
        increase=False,
        batna_floor=batna_floor,
        adjustment_percentage=adjustment_percentage,
    )
    return target, clamped, "apply_decrease_from_reference"


def state_after_apply(increase: bool, state: AdjustmentState) -> AdjustmentState:
    if state == "manual":
        return "neutral"
    if increase:
        if state == "decreased":
            return "neutral"
        return "increased"
    if state == "increased":
        return "neutral"
    return "decreased"


def resolve_adjustment_for_date(
    live_price: int,
    stored_reference: Optional[int],
    increase: bool,
    batna_floor: Optional[float],
    adjustment_percentage: float = DEFAULT_ADJUSTMENT_PERCENTAGE,
    tolerance: int = DEFAULT_TOLERANCE,
) -> Dict[str, Any]:
    """Full resolution for one date: reference, target, metadata for preview/ledger."""
    reference, state, refreshed = resolve_reference(
        live_price,
        stored_reference,
        batna_floor,
        adjustment_percentage,
        tolerance,
    )
    decreased, increased = tier_targets(reference, batna_floor, adjustment_percentage)
    target, clamped, action = compute_target_price(
        increase, reference, state, batna_floor, adjustment_percentage
    )
    return {
        "live_price": int(live_price),
        "reference_price": reference,
        "inferred_state": state,
        "reference_refreshed": refreshed,
        "decreased_target": decreased,
        "increased_target": increased,
        "new_price": target,
        "clamped": clamped,
        "action": action,
        "state_after_apply": state_after_apply(increase, state),
    }
