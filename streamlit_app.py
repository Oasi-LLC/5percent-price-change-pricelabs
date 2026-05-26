import streamlit as st
import time
import os
import pandas as pd
from typing import List, Dict
from itertools import groupby
import logging
from dotenv import load_dotenv

from pricelabs_tool.adjustment import compute_listing_adjustments
from pricelabs_tool.api_client import PriceLabsAPI
from pricelabs_tool.property_config import (
    exclude_listings_not_in_config,
    extract_parent_listing_id,
    load_property_config,
    listing_to_property,
    sort_listings_by_property,
    split_children_of_selected_update_children_parents,
)

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv('PRICELABS_API_KEY')
BASE_URL = os.getenv('API_BASE_URL', 'https://api.pricelabs.co/v1')
ADJUSTMENT_PERCENTAGE = 5  # 5% adjustment
APP_PASSWORD = os.getenv('APP_PASSWORD')  # Optional: when set, requires @stayoasi.com + this password to access

# Validation
if not API_KEY:
    st.error("PRICELABS_API_KEY environment variable is required")
    st.stop()

# Logging: INFO so we can see pulled rates and after-change rates (e.g. in terminal when running streamlit)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _st_rerun() -> None:
    """Compat: st.rerun() exists in Streamlit >=1.27; older versions use experimental_rerun."""
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()
    else:
        st.experimental_rerun()


# Retry: any failure is retried for that listing
MAX_RETRIES_PER_LISTING = 3
RETRY_BACKOFF_SECONDS = (5, 10)


# --- Helper functions ---
def fetch_listings():
    api_client = PriceLabsAPI()
    listings = api_client.get_listings()
    active_listings = [
        l for l in listings
        if not l.get('isHidden', True) and l.get('push_enabled', False)
    ]
    return active_listings

def batch_update(
    listings,
    increase,
    batch_size=10,
    delay=2,
    per_listing_delay=2,
):
    """Process listings in batches and upload adjusted overrides to PriceLabs."""
    prop_config = load_property_config()
    results = []
    listings, auto_skipped_children = split_children_of_selected_update_children_parents(
        listings, prop_config
    )
    for child in auto_skipped_children:
        parent_id = extract_parent_listing_id(child)
        msg = "Auto-skipped child listing: selected parent has update_children=true"
        if parent_id:
            msg += f" (parent_id={parent_id})"
        results.append({
            "id": child["id"],
            "name": child.get("name", str(child.get("id"))),
            "status": "skipped",
            "message": msg,
        })

    total = len(listings)
    for i in range(0, total, batch_size):
        batch = listings[i : i + batch_size]
        st.info(
            f"Processing batch {i // batch_size + 1} of "
            f"{(total + batch_size - 1) // batch_size} ({len(batch)} listings)"
        )
        for listing in batch:
            last_error = None
            for attempt in range(MAX_RETRIES_PER_LISTING):
                try:
                    api_client = PriceLabsAPI()
                    overrides = api_client.get_listing_overrides(
                        listing["id"], pms=listing.get("pms")
                    )
                    all_pulled = overrides.get("overrides", [])
                    computed = compute_listing_adjustments(
                        listing,
                        all_pulled,
                        prop_config,
                        increase=increase,
                        adjustment_percentage=ADJUSTMENT_PERCENTAGE,
                    )
                    skipped = computed["skipped"]
                    num_qualifying = computed["would_update"]
                    num_skipped = (
                        skipped["not_fixed"]
                        + skipped["date_range"]
                        + skipped["bad_price"]
                    )
                    if num_qualifying == 0:
                        msg = (
                            "No overrides in valid range (fixed, today or future, ≤1 year) to update"
                        )
                        if all_pulled:
                            msg += (
                                f". Pulled {len(all_pulled)} total (skipped: "
                                f"{skipped['not_fixed']} non-fixed, "
                                f"{skipped['date_range']} out of date range, "
                                f"{skipped['bad_price']} bad price)"
                            )
                        results.append({
                            "id": listing["id"],
                            "name": listing["name"],
                            "status": "skipped",
                            "message": msg,
                        })
                        last_error = None
                        break

                    if computed["update_children"]:
                        logger.info(
                            "listing_id=%s name=%s update_children=true (property=%s)",
                            listing.get("id"),
                            listing.get("name"),
                            computed["prop_key"],
                        )
                    api_client.update_listing_overrides(
                        listing["id"],
                        computed["adjusted_overrides"],
                        pms=listing.get("pms"),
                        update_children=computed["update_children"],
                    )

                    results.append({
                        "id": listing["id"],
                        "name": listing["name"],
                        "status": "success",
                        "dates_updated": num_qualifying,
                        "batna_clamped_count": computed["batna_clamped_count"],
                        "skipped_count": num_skipped,
                        "skipped_not_fixed": skipped["not_fixed"],
                        "skipped_date_range": skipped["date_range"],
                        "skipped_bad_price": skipped["bad_price"],
                    })
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES_PER_LISTING - 1:
                        wait = (
                            RETRY_BACKOFF_SECONDS[attempt]
                            if attempt < len(RETRY_BACKOFF_SECONDS)
                            else 10
                        )
                        logger.warning(
                            "Listing %s attempt %s failed (%s); retrying in %ss",
                            listing.get("id"),
                            attempt + 1,
                            e,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        results.append({
                            "id": listing["id"],
                            "name": listing["name"],
                            "status": "error",
                            "message": str(last_error),
                        })
                        break
            time.sleep(per_listing_delay)
        if i + batch_size < total:
            time.sleep(delay)
    return results


# --- Streamlit UI ---
st.set_page_config(page_title="PriceLabs Price Adjustment", layout="centered")

# Password protection: when APP_PASSWORD is set, only @stayoasi.com + password can access
ALLOWED_DOMAIN = "@stayoasi.com"
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if APP_PASSWORD and not st.session_state["authenticated"]:
    st.title("Sign in")
    email = st.text_input("Email", placeholder="you@stayoasi.com")
    password = st.text_input("Password", type="password", placeholder="Shared app password")
    if st.button("Sign in"):
        email_clean = (email or "").strip().lower()
        if not email_clean.endswith(ALLOWED_DOMAIN):
            st.error("Access is restricted to " + ALLOWED_DOMAIN + " addresses.")
        elif password != APP_PASSWORD:
            st.error("Incorrect password.")
        else:
            st.session_state["authenticated"] = True
            _st_rerun()
    st.stop()

st.title("PriceLabs Price Adjustment Tool")

# Logout in sidebar (only when password protection is on)
if APP_PASSWORD:
    with st.sidebar:
        if st.button("Log out"):
            st.session_state["authenticated"] = False
            _st_rerun()

# Initialize session state
if 'listings' not in st.session_state:
    st.session_state['listings'] = []
if 'failed_listings' not in st.session_state:
    st.session_state['failed_listings'] = []
if 'last_increase' not in st.session_state:
    st.session_state['last_increase'] = True

# Refresh listings button
if st.button('Refresh Listings from PriceLabs'):
    with st.spinner('Fetching latest listings...'):
        raw_listings = fetch_listings()
        prop_cfg = load_property_config()
        configured_listings, n_excluded_other = exclude_listings_not_in_config(raw_listings, prop_cfg)
        st.session_state['listings'] = configured_listings
        total_shown = len(configured_listings)
        total_api = len(raw_listings)
        st.success(
            f"Fetched {total_api} active listings from PriceLabs. "
            f"Showing {total_shown} that match properties_config.yaml."
            + (f" Excluded {n_excluded_other} not in config (child/uncatalogued listings are hidden; update parents only)." if n_excluded_other else "")
        )

        # Show summary stats
        if total_shown > 0:
            st.subheader("📊 Listings Summary")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("In config (shown)", total_shown)
            with col2:
                st.metric("Excluded (not in YAML)", n_excluded_other)

listings = st.session_state['listings']
# Drop listings not in properties_config.yaml so "Other" never appears and cannot be adjusted.
prop_config = load_property_config()
if listings:
    filtered_listings, _ = exclude_listings_not_in_config(listings, prop_config)
    if len(filtered_listings) != len(listings):
        st.session_state['listings'] = filtered_listings
    listings = st.session_state['listings']

if listings:
    sorted_listings = sort_listings_by_property(listings, prop_config)

    # Initialize checkbox state for all listings (default True) so we only use session state, not value=
    for L in sorted_listings:
        st.session_state.setdefault("cb_" + str(L["id"]), True)

    # Checkboxes inside a dropdown (expander)
    n_selected = sum(1 for L in sorted_listings if st.session_state.get("cb_" + str(L["id"]), True))
    # Keep expander open (expanded=True) so it doesn't close on checkbox click and force repeated scroll to FLOHOM etc.
    with st.expander(f"Select listings to adjust ({n_selected} selected)", expanded=True):
        # Equal-width columns and min-width on buttons so "Deselect all" doesn't wrap and both match size
        st.markdown(
            """<style>
            [data-testid="stExpander"] [data-testid="column"]:nth-child(1) button,
            [data-testid="stExpander"] [data-testid="column"]:nth-child(2) button { min-width: 7.5rem; }
            </style>""",
            unsafe_allow_html=True,
        )
        col_sel, col_desel = st.columns(2)
        with col_sel:
            if st.button("Select all", key="select_all_listings"):
                for L in sorted_listings:
                    st.session_state["cb_" + str(L["id"])] = True
                _st_rerun()
        with col_desel:
            if st.button("Deselect all", key="deselect_all_listings"):
                for L in sorted_listings:
                    st.session_state["cb_" + str(L["id"])] = False
                _st_rerun()

        def _property_display_name(L: Dict) -> str:
            return listing_to_property(L.get("id"), prop_config)[1]

        for prop_display_name, group in groupby(sorted_listings, key=_property_display_name):
            st.markdown(f"**{prop_display_name}**")
            for listing in group:
                cb_key = "cb_" + str(listing["id"])
                st.checkbox(
                    listing.get("name", listing["id"]),
                    key=cb_key,
                )
            st.divider()

    # Selected = checkboxes that are checked
    selected_listing_objects = [
        L for L in sorted_listings
        if st.session_state.get("cb_" + str(L["id"]), True)
    ]

    if selected_listing_objects:
        st.subheader("Adjustment options")

        adjustment_type = st.radio(
            "Choose adjustment type:",
            ["Increase by 5%", "Decrease by 5%"],
        )
        increase = adjustment_type == "Increase by 5%"

        if st.button("Apply Price Adjustments", type="primary"):
            st.info("Applying changes...")
            results = batch_update(selected_listing_objects, increase)

            st.session_state["failed_listings"] = [r for r in results if r["status"] == "error"]
            st.session_state["last_increase"] = increase

            successful = len([r for r in results if r["status"] == "success"])
            failed = len([r for r in results if r["status"] == "error"])
            skipped = len([r for r in results if r["status"] == "skipped"])
            total = len(results)

            st.subheader("Results")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Processed", total)
            with col2:
                st.metric("Successful", successful, delta=f"+{successful}" if successful else None)
            with col3:
                st.metric("Failed", failed, delta=f"-{failed}" if failed else None)
            with col4:
                st.metric("Skipped", skipped, delta=f"-{skipped}" if skipped else None)

            for result in results:
                if result["status"] == "success":
                    n = result.get("dates_updated", 0)
                    skip = result.get("skipped_count", 0)
                    batna_n = result.get("batna_clamped_count", 0)
                    batna_note = f" {batna_n} date(s) set to BATNA floor." if batna_n else ""
                    if skip:
                        parts = []
                        if result.get("skipped_not_fixed"):
                            parts.append(f"{result['skipped_not_fixed']} non-fixed")
                        if result.get("skipped_date_range"):
                            parts.append(f"{result['skipped_date_range']} out of date range")
                        if result.get("skipped_bad_price"):
                            parts.append(f"{result['skipped_bad_price']} bad price")
                        st.success(
                            f"✅ {result['name']}: All {n} date(s) updated.{batna_note} "
                            f"{skip} override(s) in PriceLabs not changed: {', '.join(parts)}."
                        )
                    else:
                        st.success(
                            f"✅ {result['name']}: All {n} date(s) updated successfully.{batna_note}"
                        )
                elif result["status"] == "skipped":
                    st.warning(f"⏭️ {result['name']}: {result.get('message', 'Skipped')}")
                else:
                    st.error(f"❌ {result['name']}: {result['message']}")

    # Failed listings table and manual retry (shown whenever there are stored failures)
    failed_listings = st.session_state.get('failed_listings', [])
    if failed_listings:
        st.subheader("Failed listings (retry manually)")
        # Table: Name, Listing ID, Error
        failed_df = pd.DataFrame([
            {"Name": r["name"], "Listing ID": r["id"], "Error": r.get("message", "")}
            for r in failed_listings
        ])
        st.dataframe(failed_df, use_container_width=True, hide_index=True)
        if st.button("Retry failed listings", key="retry_failed_listings"):
            # Resolve full listing objects from current listings by id
            failed_ids = {r["id"] for r in failed_listings}
            retry_objects = [L for L in sorted_listings if L.get("id") in failed_ids]
            if not retry_objects:
                st.warning("Could not find listing details for failed IDs. Click 'Refresh Listings from PriceLabs' and try again.")
            else:
                with st.spinner("Retrying failed listings..."):
                    retry_results = batch_update(retry_objects, st.session_state['last_increase'])
                still_failed = [r for r in retry_results if r['status'] == 'error']
                st.session_state['failed_listings'] = still_failed
                retried_ok = len(retry_results) - len(still_failed)
                if still_failed:
                    st.warning(f"Retry complete: {retried_ok} succeeded, {len(still_failed)} still failed.")
                else:
                    st.success(f"All {len(retry_results)} listings updated successfully.")
                _st_rerun()
else:
    st.info('Click "Refresh Listings from PriceLabs" to begin.') 