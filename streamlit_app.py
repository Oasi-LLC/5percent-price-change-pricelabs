import streamlit as st
import time
import os
import requests
import yaml
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime, timedelta
from itertools import groupby
import logging
from dotenv import load_dotenv

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

class PriceLabsAPI:
    def __init__(self):
        self.api_key = API_KEY
        if not self.api_key:
            raise ValueError("PRICELABS_API_KEY environment variable is required")
        
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': self.api_key,
            'Content-Type': 'application/json'
        })

    def get_listings(self) -> List[Dict]:
        """Get all active listings"""
        response = self.session.get(f"{self.base_url}/listings")
        response.raise_for_status()
        
        data = response.json()
        return data.get('listings', []) if isinstance(data, dict) else []

    def get_listing_overrides(self, listing_id: str, pms: str = None) -> Dict:
        """Fetch overrides for a specific listing"""
        try:
            params = {}
            if pms:
                params['pms'] = pms
                
            response = self.session.get(
                f"{self.base_url}/listings/{listing_id}/overrides",
                params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching overrides for listing {listing_id}: {e}")
            raise

    def update_listing_overrides(
        self,
        listing_id: str,
        overrides: List[Dict],
        pms: str = None,
        update_children: bool = False
    ) -> Dict:
        """Update listing overrides with new prices"""
        try:
            payload = {
                "update_children": update_children,
                "overrides": overrides
            }
            if pms:
                payload['pms'] = pms

            response = self.session.post(
                f"{self.base_url}/listings/{listing_id}/overrides",
                json=payload
            )
            
            if not response.ok:
                error_detail = response.json() if response.content else "No error details"
                logger.error(f"API error response: {error_detail}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error updating overrides for listing {listing_id}: {e}")
            raise

def calculate_adjusted_price(price: float, increase: bool = True) -> float:
    """Adjust the price by the configured percentage."""
    if increase:
        return price * (1 + ADJUSTMENT_PERCENTAGE / 100)
    else:
        return price * (1 - ADJUSTMENT_PERCENTAGE / 100)


def _is_date_in_valid_range(date_str: str) -> bool:
    """PriceLabs API: date must be in future and less than 1 year from today."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    today = datetime.now().date()
    one_year_later = today + timedelta(days=365)
    return today < d <= one_year_later

# --- Property config (for grouping/sorting) ---
def _load_property_config() -> Dict:
    """Load properties_config.yaml; return {} if missing. Supports top-level 'properties:' key."""
    path = Path(__file__).resolve().parent / "properties_config.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("properties", data)


def _listing_to_property(listing_id: str, config: Dict) -> Tuple[str, str]:
    """Return (sort_key, display_name) for the listing's property. Unknown -> ('zz_Other', 'Other')."""
    lid = str(listing_id)
    for prop_key, prop_data in config.items():
        if not isinstance(prop_data, dict):
            continue
        for entry in prop_data.get("listings", []):
            if str(entry.get("id")) == lid:
                return (prop_key, prop_data.get("name", prop_key))
    return ("zz_Other", "Other")


# Retry: any failure is retried for that listing
MAX_RETRIES_PER_LISTING = 3
RETRY_BACKOFF_SECONDS = (5, 10)  # wait 5s after first failure, 10s after second


def _sort_listings_by_property(listings: List[Dict], config: Dict) -> List[Dict]:
    """Sort by property (same property together), then by listing name."""
    return sorted(
        listings,
        key=lambda L: (
            _listing_to_property(L.get("id"), config)[0],
            _listing_to_property(L.get("id"), config)[1],
            (L.get("name") or ""),
        ),
    )

def _extract_parent_listing_id(listing: Dict) -> Optional[str]:
    """Best-effort parent ID extraction from API listing payload."""
    direct_keys = (
        "parent_listing_id",
        "parentListingId",
        "parent_id",
        "parentId",
        "parent",
    )
    for key in direct_keys:
        value = listing.get(key)
        if value:
            if isinstance(value, dict):
                nested_id = value.get("id")
                if nested_id:
                    return str(nested_id)
            else:
                return str(value)
    return None


def _split_children_of_selected_update_children_parents(listings: List[Dict], prop_config: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Keep selected listings except children whose selected parent will already propagate changes.
    Returns (to_process, auto_skipped_children).
    """
    configured_listing_ids: Set[str] = set()
    selected_update_children_parent_ids: Set[str] = set()

    for L in listings:
        lid = str(L.get("id"))
        prop_key = _listing_to_property(lid, prop_config)[0]
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
        # Only auto-skip unknown "Other" listings that reference a selected update_children parent.
        if lid not in configured_listing_ids:
            parent_id = _extract_parent_listing_id(L)
            if parent_id and parent_id in selected_update_children_parent_ids:
                auto_skipped_children.append(L)
                continue
        to_process.append(L)

    return to_process, auto_skipped_children


# --- Helper functions ---
def fetch_listings():
    api_client = PriceLabsAPI()
    listings = api_client.get_listings()
    active_listings = [
        l for l in listings
        if not l.get('isHidden', True) and l.get('push_enabled', False)
    ]
    return active_listings

def batch_update(listings, increase, batch_size=10, delay=2, per_listing_delay=2):
    """Process listings in batches with per-listing and between-batch delays to avoid rate limits.
    batch_size=10 keeps request bursts smaller; per_listing_delay=2 ~1 req/sec per listing. Increase delay if you see 429s."""
    prop_config = _load_property_config()
    results = []
    listings, auto_skipped_children = _split_children_of_selected_update_children_parents(listings, prop_config)
    for child in auto_skipped_children:
        parent_id = _extract_parent_listing_id(child)
        msg = "Auto-skipped child listing: selected parent has update_children=true"
        if parent_id:
            msg += f" (parent_id={parent_id})"
        results.append({
            'id': child['id'],
            'name': child.get('name', str(child.get('id'))),
            'status': 'skipped',
            'message': msg
        })

    total = len(listings)
    for i in range(0, total, batch_size):
        batch = listings[i:i+batch_size]
        st.info(f"Processing batch {i//batch_size+1} of {(total+batch_size-1)//batch_size} ({len(batch)} listings)")
        for listing in batch:
            last_error = None
            for attempt in range(MAX_RETRIES_PER_LISTING):
                try:
                    api_client = PriceLabsAPI()
                    overrides = api_client.get_listing_overrides(listing['id'], pms=listing.get('pms'))
                    all_pulled = overrides.get('overrides', [])
                    logger.info(
                        "listing_id=%s name=%s pulled_overrides_count=%s sample=%s",
                        listing.get('id'), listing.get('name'), len(all_pulled),
                        [(o.get('date'), o.get('price'), o.get('price_type')) for o in all_pulled[:5]]
                    )
                    adjusted_overrides = []
                    skipped_not_fixed = 0
                    skipped_date_range = 0
                    skipped_bad_price = 0
                    pulled_qualifying = []  # (date, old_price) for logging
                    for override in all_pulled:
                        if override.get('price_type') != 'fixed':
                            skipped_not_fixed += 1
                            continue
                        if not _is_date_in_valid_range(override.get('date', '')):
                            skipped_date_range += 1
                            continue
                        old_price = float(override.get('price', 0))
                        if old_price <= 0:
                            skipped_bad_price += 1
                            continue
                        new_price = calculate_adjusted_price(old_price, increase=increase)
                        pulled_qualifying.append((override['date'], old_price, new_price))
                        adjusted_overrides.append({
                            'date': override['date'],
                            'price': str(int(new_price)),
                            'price_type': 'fixed',
                            'currency': override.get('currency', 'USD'),
                            'min_stay': override.get('min_stay', 1)
                        })
                    num_qualifying = len(adjusted_overrides)
                    if pulled_qualifying:
                        sample = [(d, f"{p_old:.0f}->{p_new:.0f}") for d, p_old, p_new in pulled_qualifying[:10]]
                        logger.info(
                            "listing_id=%s name=%s after_change sample_rates=%s direction=%s",
                            listing.get('id'), listing.get('name'), sample, "increase" if increase else "decrease"
                        )
                    num_skipped = skipped_not_fixed + skipped_date_range + skipped_bad_price
                    if num_qualifying == 0:
                        msg = 'No overrides in valid range (fixed, future, ≤1 year) to update'
                        if all_pulled:
                            msg += f'. Pulled {len(all_pulled)} total (skipped: {skipped_not_fixed} non-fixed, {skipped_date_range} out of date range, {skipped_bad_price} bad price)'
                        results.append({
                            'id': listing['id'],
                            'name': listing['name'],
                            'status': 'skipped',
                            'message': msg
                        })
                        last_error = None
                        break
                    # Send the full set of qualifying overrides; success only if we update all of them
                    # Some properties (e.g. FLOHOM/Hostaway) need update_children=True for changes to appear
                    prop_key = _listing_to_property(str(listing.get('id')), prop_config)[0]
                    prop_data = prop_config.get(prop_key) if isinstance(prop_config.get(prop_key), dict) else {}
                    update_children = prop_data.get('update_children', False)
                    if update_children:
                        logger.info("listing_id=%s name=%s update_children=true (property=%s)", listing.get('id'), listing.get('name'), prop_key)
                    api_client.update_listing_overrides(
                        listing['id'], adjusted_overrides, pms=listing.get('pms'), update_children=update_children
                    )
                    results.append({
                        'id': listing['id'],
                        'name': listing['name'],
                        'status': 'success',
                        'dates_updated': num_qualifying,
                        'skipped_count': num_skipped,
                        'skipped_not_fixed': skipped_not_fixed,
                        'skipped_date_range': skipped_date_range,
                        'skipped_bad_price': skipped_bad_price
                    })
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < MAX_RETRIES_PER_LISTING - 1:
                        wait = RETRY_BACKOFF_SECONDS[attempt] if attempt < len(RETRY_BACKOFF_SECONDS) else 10
                        logger.warning(f"Listing {listing.get('id')} attempt {attempt + 1} failed ({e}); retrying in {wait}s")
                        time.sleep(wait)
                    else:
                        results.append({
                            'id': listing['id'],
                            'name': listing['name'],
                            'status': 'error',
                            'message': str(last_error)
                        })
                        break
            # Throttle after each listing to avoid rate limits
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
            st.rerun()
    st.stop()

st.title("PriceLabs Price Adjustment Tool")

# Logout in sidebar (only when password protection is on)
if APP_PASSWORD:
    with st.sidebar:
        if st.button("Log out"):
            st.session_state["authenticated"] = False
            st.rerun()

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
        st.session_state['listings'] = fetch_listings()
        total_listings = len(st.session_state['listings'])
        st.success(f"Fetched {total_listings} active listings.")
        
        # Show summary stats
        if total_listings > 0:
            st.subheader("📊 Listings Summary")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Active Listings", total_listings)
            with col2:
                st.metric("Ready for Adjustment", total_listings)

listings = st.session_state['listings']

if listings:
    prop_config = _load_property_config()
    sorted_listings = _sort_listings_by_property(listings, prop_config)

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
                st.rerun()
        with col_desel:
            if st.button("Deselect all", key="deselect_all_listings"):
                for L in sorted_listings:
                    st.session_state["cb_" + str(L["id"])] = False
                st.rerun()

        def _property_display_name(L: Dict) -> str:
            return _listing_to_property(L.get("id"), prop_config)[1]

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
        st.subheader("Adjustment Options")
        
        # Adjustment type
        adjustment_type = st.radio(
            "Choose adjustment type:",
            ["Increase by 5%", "Decrease by 5%"]
        )
        increase = adjustment_type == "Increase by 5%"
        
        # Apply button
        if st.button("Apply Price Adjustments", type="primary"):
            st.info("Applying changes...")
            results = batch_update(selected_listing_objects, increase)
            
            # Store failed listings (errors only; skipped are not retryable) and last adjustment direction
            st.session_state['failed_listings'] = [r for r in results if r['status'] == 'error']
            st.session_state['last_increase'] = increase
            
            # Calculate totals
            successful = len([r for r in results if r['status'] == 'success'])
            failed = len([r for r in results if r['status'] == 'error'])
            skipped = len([r for r in results if r['status'] == 'skipped'])
            total = len(results)
            
            st.subheader("Results")
            
            # Summary stats: success = all qualifying dates for that listing were updated
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Processed", total)
            with col2:
                st.metric("Successful", successful, delta=f"+{successful}" if successful else None)
            with col3:
                st.metric("Failed", failed, delta=f"-{failed}" if failed else None)
            with col4:
                st.metric("Skipped", skipped, delta=f"-{skipped}" if skipped else None)
            
            # Individual results: success means all pulled qualifying dates were updated
            for result in results:
                if result['status'] == 'success':
                    n = result.get('dates_updated', 0)
                    skip = result.get('skipped_count', 0)
                    if skip:
                        parts = []
                        if result.get('skipped_not_fixed'):
                            parts.append(f"{result['skipped_not_fixed']} non-fixed")
                        if result.get('skipped_date_range'):
                            parts.append(f"{result['skipped_date_range']} out of date range")
                        if result.get('skipped_bad_price'):
                            parts.append(f"{result['skipped_bad_price']} bad price")
                        st.success(f"✅ {result['name']}: All {n} date(s) updated. {skip} override(s) in PriceLabs not changed: {', '.join(parts)}.")
                    else:
                        st.success(f"✅ {result['name']}: All {n} date(s) updated successfully")
                elif result['status'] == 'skipped':
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
                st.rerun()
else:
    st.info('Click "Refresh Listings from PriceLabs" to begin.') 