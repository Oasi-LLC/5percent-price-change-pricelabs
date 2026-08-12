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


def test_blueridge_orbirental_mirror_mapping():
    config = _load_prop_config()
    wellness_orbirental = "3527b9f8-e4db-4220-8f47-f41ecda4d983"
    wellness_guesty = "6a74a4b9067fda0013c87525"
    aframe_orbirental = "0dfcb2d6-226c-4a4a-a6eb-378ef134cd94"
    aframe_guesty = "6a74a4c0067fda0013c8769e"

    assert mirror_rates_from_listing_id(wellness_orbirental, config) == wellness_guesty
    assert mirror_rates_from_listing_id(aframe_orbirental, config) == aframe_guesty
    assert is_mirror_listing(wellness_orbirental, config) is True
    assert is_mirror_listing(wellness_guesty, config) is False
    assert listing_pms(wellness_orbirental, config) == "orbirental"
    assert listing_pms(wellness_guesty, config) == "guesty"


def test_mirror_targets_for_source():
    config = _load_prop_config()
    wellness_guesty = "6a74a4b9067fda0013c87525"
    targets = mirror_targets_for_source(wellness_guesty, config)
    assert len(targets) == 1
    assert targets[0]["id"] == "3527b9f8-e4db-4220-8f47-f41ecda4d983"
    assert targets[0]["pms"] == "orbirental"


def test_partition_adjust_and_mirror_listings():
    config = _load_prop_config()
    listings = [
        {"id": "6a74a4b9067fda0013c87525", "name": "Guesty wellness"},
        {"id": "3527b9f8-e4db-4220-8f47-f41ecda4d983", "name": "Orbirental wellness"},
        {"id": "320203", "name": "Sunstrip"},
    ]
    adjust, mirror_only = partition_adjust_and_mirror_listings(listings, config)
    assert [L["id"] for L in adjust] == ["6a74a4b9067fda0013c87525", "320203"]
    assert [L["id"] for L in mirror_only] == ["3527b9f8-e4db-4220-8f47-f41ecda4d983"]
