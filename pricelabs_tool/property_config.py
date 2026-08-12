"""Load and query properties_config.yaml."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_property_config() -> Dict:
    path = PROJECT_ROOT / "properties_config.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("properties", data)


def listing_to_property(listing_id: str, config: Dict) -> Tuple[str, str]:
    lid = str(listing_id)
    for prop_key, prop_data in config.items():
        if not isinstance(prop_data, dict):
            continue
        for entry in prop_data.get("listings", []):
            if str(entry.get("id")) == lid:
                return prop_key, prop_data.get("name", prop_key)
    return "zz_Other", "Other"


def get_listing_entry(listing_id: str, config: Dict) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Return (listing entry, property data) for a configured listing id."""
    lid = str(listing_id)
    for prop_data in config.values():
        if not isinstance(prop_data, dict):
            continue
        for entry in prop_data.get("listings", []):
            if str(entry.get("id")) == lid:
                return entry, prop_data
    return None, None


def mirror_rates_from_listing_id(listing_id: str, config: Dict) -> Optional[str]:
    entry, _ = get_listing_entry(listing_id, config)
    if not entry:
        return None
    source_id = entry.get("mirror_rates_from")
    return str(source_id) if source_id else None


def is_mirror_listing(listing_id: str, config: Dict) -> bool:
    return mirror_rates_from_listing_id(listing_id, config) is not None


def mirror_targets_for_source(source_listing_id: str, config: Dict) -> List[Dict]:
    """Configured mirror targets that copy rates from source_listing_id."""
    source_id = str(source_listing_id)
    targets: List[Dict] = []
    for prop_key, prop_data in config.items():
        if not isinstance(prop_data, dict):
            continue
        for entry in prop_data.get("listings", []):
            if str(entry.get("mirror_rates_from")) != source_id:
                continue
            targets.append({
                "id": str(entry.get("id")),
                "name": entry.get("name", entry.get("id")),
                "pms": prop_data.get("pms"),
                "prop_key": prop_key,
                "prop_name": prop_data.get("name", prop_key),
            })
    return targets


def listing_pms(listing_id: str, config: Dict) -> Optional[str]:
    _, prop_data = get_listing_entry(listing_id, config)
    if not prop_data:
        return None
    pms = prop_data.get("pms")
    return str(pms) if pms else None


def partition_adjust_and_mirror_listings(
    listings: List[Dict], prop_config: Dict
) -> Tuple[List[Dict], List[Dict]]:
    """Split selected listings into adjust vs mirror-only (mirror_rates_from)."""
    adjust: List[Dict] = []
    mirror_only: List[Dict] = []
    for listing in listings:
        lid = str(listing.get("id"))
        if is_mirror_listing(lid, prop_config):
            mirror_only.append(listing)
        else:
            adjust.append(listing)
    return adjust, mirror_only


def listing_units(listing_id: str, config: Dict) -> int:
    """Return configured unit count for a listing (defaults to 1)."""
    lid = str(listing_id)
    for prop_data in config.values():
        if not isinstance(prop_data, dict):
            continue
        for entry in prop_data.get("listings", []):
            if str(entry.get("id")) == lid:
                units = entry.get("units", 1)
                try:
                    return max(1, int(units))
                except (TypeError, ValueError):
                    return 1
    return 1


def is_date_in_valid_range(date_str: str) -> bool:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    today = datetime.now().date()
    one_year_later = today + timedelta(days=365)
    return today <= d <= one_year_later


def sort_listings_by_property(listings: List[Dict], config: Dict) -> List[Dict]:
    return sorted(
        listings,
        key=lambda L: (
            listing_to_property(L.get("id"), config)[0],
            listing_to_property(L.get("id"), config)[1],
            (L.get("name") or ""),
        ),
    )


def exclude_listings_not_in_config(
    listings: List[Dict], prop_config: Dict
) -> Tuple[List[Dict], int]:
    kept = [
        L
        for L in listings
        if listing_to_property(str(L.get("id")), prop_config)[0] != "zz_Other"
    ]
    return kept, len(listings) - len(kept)


def extract_parent_listing_id(listing: Dict) -> Optional[str]:
    for key in (
        "parent_listing_id",
        "parentListingId",
        "parent_id",
        "parentId",
        "parent",
    ):
        value = listing.get(key)
        if value:
            if isinstance(value, dict):
                nested_id = value.get("id")
                if nested_id:
                    return str(nested_id)
            else:
                return str(value)
    return None


def split_children_of_selected_update_children_parents(
    listings: List[Dict], prop_config: Dict
) -> Tuple[List[Dict], List[Dict]]:
    configured_listing_ids: Set[str] = set()
    selected_update_children_parent_ids: Set[str] = set()

    for L in listings:
        lid = str(L.get("id"))
        prop_key = listing_to_property(lid, prop_config)[0]
        if prop_key == "zz_Other":
            continue
        configured_listing_ids.add(lid)
        prop_data = prop_config.get(prop_key) if isinstance(prop_config.get(prop_key), dict) else {}
        if prop_data.get("update_children", False):
            selected_update_children_parent_ids.add(lid)

    to_process: List[Dict] = []
    auto_skipped_children: List[Dict] = []
    for L in listings:
        lid = str(L.get("id"))
        if lid not in configured_listing_ids:
            parent_id = extract_parent_listing_id(L)
            if parent_id and parent_id in selected_update_children_parent_ids:
                auto_skipped_children.append(L)
                continue
        to_process.append(L)

    return to_process, auto_skipped_children
