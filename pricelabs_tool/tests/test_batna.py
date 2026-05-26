import yaml
from pathlib import Path

from pricelabs_tool.batna import (
    apply_adjustment_with_batna,
    batna_floor_for_date,
    is_weekend_day,
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


def test_batna_floor_for_date_onera():
    config = _load_prop_config()
    floor = batna_floor_for_date("203812___362535", "2026-06-01", config)
    assert floor == 189.0


def test_batna_floor_for_date_lafave_no_batna():
    config = _load_prop_config()
    assert batna_floor_for_date("4140___8117", "2026-04-01", config) is None


def test_is_weekend_day():
    assert is_weekend_day(4) is True   # Friday
    assert is_weekend_day(5) is True   # Saturday
    assert is_weekend_day(6) is False  # Sunday
    assert is_weekend_day(0) is False  # Monday


def test_sos_weekday_weekend_batna():
    config = _load_prop_config()
    listing_id = "68642480da9649000fc63fc5"  # 12BR, weekday 750 weekend 1000
    assert batna_floor_for_date(listing_id, "2026-05-21", config) == 750.0  # Thu
    assert batna_floor_for_date(listing_id, "2026-05-22", config) == 1000.0  # Fri
    assert batna_floor_for_date(listing_id, "2026-05-24", config) == 750.0  # Sun
    assert batna_floor_for_date(listing_id, "2026-05-23", config) == 1000.0  # Sat


def test_sos_weekend_clamp_on_decrease():
    config = _load_prop_config()
    listing_id = "686424c7c8d43b001321df29"  # 11BR weekend 900
    floor = batna_floor_for_date(listing_id, "2026-05-23", config)  # Saturday
    final, clamped = apply_adjustment_with_batna(850, increase=False, batna_floor=floor)
    assert final == 900
    assert clamped is True
