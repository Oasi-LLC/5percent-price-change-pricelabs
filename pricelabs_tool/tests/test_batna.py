import yaml
from pathlib import Path

from pricelabs_tool.batna import (
    apply_adjustment_with_batna,
    batna_floor_for_date,
    batna_tier_multiplier,
    three_tier_batna_floor,
)


def _load_prop_config():
    path = Path(__file__).resolve().parents[2] / "properties_config.yaml"
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("properties", data)


def test_flat_batna_decrease_clamp():
    final, clamped = apply_adjustment_with_batna(198, increase=False, batna_floor=189.0)
    assert final == 189
    assert clamped is True


def test_flat_batna_decrease_no_clamp():
    final, clamped = apply_adjustment_with_batna(220, increase=False, batna_floor=189.0)
    assert final == 209
    assert clamped is False


def test_flat_batna_increase_clamp():
    final, clamped = apply_adjustment_with_batna(170, increase=True, batna_floor=189.0)
    assert final == 189
    assert clamped is True


def test_great_lodge_decrease_clamp():
    """BATNA 1352: 1400 * 0.95 = 1330 -> floor 1352."""
    final, clamped = apply_adjustment_with_batna(
        1400, increase=False, batna_floor=1352.0
    )
    assert final == 1352
    assert clamped is True


def test_no_batna_floor():
    final, clamped = apply_adjustment_with_batna(100, increase=False, batna_floor=None)
    assert final == 95
    assert clamped is False


def test_batna_floor_for_date_onera_mon_wed():
    config = _load_prop_config()
    floor = batna_floor_for_date("203812___362535", "2026-06-01", config)  # Monday
    assert floor == 189.0


def test_batna_floor_for_date_onera_thu_sun():
    config = _load_prop_config()
    listing_id = "203812___362535"  # Cocoon, base 189
    assert batna_floor_for_date(listing_id, "2026-06-04", config) == 217.0  # Thu
    assert batna_floor_for_date(listing_id, "2026-06-07", config) == 217.0  # Sun


def test_batna_floor_for_date_onera_fri_sat():
    config = _load_prop_config()
    listing_id = "203812___362535"
    assert batna_floor_for_date(listing_id, "2026-06-05", config) == 250.0  # Fri
    assert batna_floor_for_date(listing_id, "2026-06-06", config) == 250.0  # Sat


def test_malvern_batna_exempt_ranges():
    config = _load_prop_config()
    malvern = "389561"
    assert batna_floor_for_date(malvern, "2026-06-10", config) is None
    assert batna_floor_for_date(malvern, "2026-07-15", config) is None
    assert batna_floor_for_date(malvern, "2026-08-03", config) is None
    assert batna_floor_for_date(malvern, "2026-10-20", config) is None
    assert batna_floor_for_date(malvern, "2026-06-05", config) == 794.0  # Fri
    assert batna_floor_for_date(malvern, "2026-06-20", config) == 794.0  # Sat
    assert batna_floor_for_date(malvern, "2026-07-02", config) == 690.0  # Thu
    assert batna_floor_for_date(malvern, "2026-08-06", config) == 690.0  # Thu


def test_malvern_exempt_date_no_batna_clamp():
    config = _load_prop_config()
    final, clamped = apply_adjustment_with_batna(
        550, increase=False, batna_floor=batna_floor_for_date("389561", "2026-06-10", config)
    )
    assert final == 522
    assert clamped is False


def test_batna_floor_for_date_unknown_listing():
    config = _load_prop_config()
    assert batna_floor_for_date("4140___8117", "2026-04-01", config) is None


def test_batna_tier_multiplier():
    assert batna_tier_multiplier(0) == 1.0    # Monday
    assert batna_tier_multiplier(2) == 1.0    # Wednesday
    assert batna_tier_multiplier(3) == 1.15   # Thursday
    assert batna_tier_multiplier(6) == 1.15   # Sunday
    assert batna_tier_multiplier(4) == 1.15 ** 2  # Friday
    assert batna_tier_multiplier(5) == 1.15 ** 2  # Saturday


def test_three_tier_batna_floor():
    assert three_tier_batna_floor(200, 0) == 200
    assert three_tier_batna_floor(200, 3) == 230
    assert three_tier_batna_floor(200, 4) == 264


def test_blueridge_weekday_weekend_batna():
    config = _load_prop_config()
    listing_id = "3527b9f8-e4db-4220-8f47-f41ecda4d983"  # Little Luxe, weekday 200 weekend 300
    assert batna_floor_for_date(listing_id, "2026-05-19", config) == 200.0  # Tue
    assert batna_floor_for_date(listing_id, "2026-05-21", config) == 200.0  # Thu
    assert batna_floor_for_date(listing_id, "2026-05-22", config) == 300.0  # Fri
    assert batna_floor_for_date(listing_id, "2026-05-24", config) == 200.0  # Sun
    assert batna_floor_for_date(listing_id, "2026-05-23", config) == 300.0  # Sat


def test_blueridge_weekend_clamp_on_decrease():
    config = _load_prop_config()
    listing_id = "0dfcb2d6-226c-4a4a-a6eb-378ef134cd94"  # A-Frame weekend 800
    floor = batna_floor_for_date(listing_id, "2026-05-23", config)  # Saturday
    final, clamped = apply_adjustment_with_batna(750, increase=False, batna_floor=floor)
    assert floor == 800.0
    assert final == 800
    assert clamped is True
