import streamlit as st
import os
import pandas as pd
from typing import List, Dict
from itertools import groupby
import logging
from dotenv import load_dotenv

from pricelabs_tool.batch_runner import (
    AdjustmentRunInProgressError,
    batch_update,
    fetch_active_listings,
)
from pricelabs_tool.property_config import (
    exclude_listings_not_in_config,
    load_property_config,
    listing_to_property,
    mirror_rates_from_listing_id,
    sort_listings_by_property,
)

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv('PRICELABS_API_KEY')
BASE_URL = os.getenv('API_BASE_URL', 'https://api.pricelabs.co/v1')
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
        raw_listings = fetch_active_listings()
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
                label = listing.get("name", listing["id"])
                source_id = mirror_rates_from_listing_id(str(listing["id"]), prop_config)
                if source_id:
                    label += f" (mirrors {source_id})"
                st.checkbox(
                    label,
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
            try:
                results = batch_update(
                    selected_listing_objects,
                    increase,
                    progress_callback=st.info,
                )
            except AdjustmentRunInProgressError as e:
                st.error(str(e))
                st.stop()

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
                    verified = result.get("dates_verified", n)
                    skip = result.get("skipped_count", 0)
                    batna_n = result.get("batna_clamped_count", 0)
                    already = result.get("already_adjusted_count", 0)
                    batna_note = f" {batna_n} date(s) set to BATNA floor." if batna_n else ""
                    verified_note = f" {verified} date(s) verified." if verified else ""
                    already_note = (
                        f" {already} date(s) already at target (skipped)." if already else ""
                    )
                    if skip:
                        parts = []
                        if result.get("skipped_booked"):
                            parts.append(f"{result['skipped_booked']} booked")
                        if result.get("skipped_not_fixed"):
                            parts.append(f"{result['skipped_not_fixed']} non-fixed")
                        if result.get("skipped_date_range"):
                            parts.append(f"{result['skipped_date_range']} out of date range")
                        if result.get("skipped_bad_price"):
                            parts.append(f"{result['skipped_bad_price']} bad price")
                        st.success(
                            f"✅ {result['name']}: All {n} date(s) updated.{batna_note}{verified_note}{already_note} "
                            f"{skip} override(s) in PriceLabs not changed: {', '.join(parts)}."
                        )
                    else:
                        st.success(
                            f"✅ {result['name']}: All {n} date(s) updated successfully.{batna_note}{verified_note}{already_note}"
                        )
                elif result["status"] == "skipped":
                    st.warning(f"⏭️ {result['name']}: {result.get('message', 'Skipped')}")
                else:
                    prefix = ""
                    if result.get("verification_failed"):
                        prefix = "⚠️ Verification failed: "
                    st.error(f"❌ {result['name']}: {prefix}{result['message']}")

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
                    try:
                        retry_results = batch_update(
                            retry_objects,
                            st.session_state['last_increase'],
                            progress_callback=st.info,
                        )
                    except AdjustmentRunInProgressError as e:
                        st.error(str(e))
                        st.stop()
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