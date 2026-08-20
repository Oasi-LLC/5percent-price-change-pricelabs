import yaml
from pathlib import Path

from pricelabs_tool.property_config import (
    is_mirror_listing,
    listing_pms,
    mirror_rates_from_listing_id,
    mirror_targets_for_source,
    partition_adjust_and_mirror_listings,
)


def _load_prop_config():
    path = Path(__file__).resolve().parents[2] / "properties_config.yaml"
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("properties", data)


def test_blueridge_orbirental_commented_out():
    """Orbirental Blue Ridge is excluded; Guesty stays active with no mirror targets."""
    config = _load_prop_config()
    wellness_orbirental = "3527b9f8-e4db-4220-8f47-f41ecda4d983"
    wellness_guesty = "6a74a4b9067fda0013c87525"
    aframe_orbirental = "0dfcb2d6-226c-4a4a-a6eb-378ef134cd94"
    aframe_guesty = "6a74a4c0067fda0013c8769e"

    assert "blueridge_orbirental" not in config
    assert mirror_rates_from_listing_id(wellness_orbirental, config) is None
    assert mirror_rates_from_listing_id(aframe_orbirental, config) is None
    assert is_mirror_listing(wellness_orbirental, config) is False
    assert is_mirror_listing(wellness_guesty, config) is False
    assert listing_pms(wellness_orbirental, config) is None
    assert listing_pms(wellness_guesty, config) == "guesty"
    assert listing_pms(aframe_guesty, config) == "guesty"
    assert mirror_targets_for_source(wellness_guesty, config) == []
    assert mirror_targets_for_source(aframe_guesty, config) == []


def test_partition_with_no_active_mirrors():
    config = _load_prop_config()
    listings = [
        {"id": "6a74a4b9067fda0013c87525", "name": "Guesty wellness"},
        {"id": "3527b9f8-e4db-4220-8f47-f41ecda4d983", "name": "Orbirental wellness"},
        {"id": "320203", "name": "Sunstrip"},
    ]
    adjust, mirror_only = partition_adjust_and_mirror_listings(listings, config)
    assert [L["id"] for L in adjust] == [
        "6a74a4b9067fda0013c87525",
        "3527b9f8-e4db-4220-8f47-f41ecda4d983",
        "320203",
    ]
    assert mirror_only == []
