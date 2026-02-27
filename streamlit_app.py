import streamlit as st
import time
import os
import requests
import yaml
from pathlib import Path
from typing import List, Dict, Optional, Tuple
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
            raise Exception(f"Error fetching overrides: {e}")

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
            raise Exception(f"Error updating overrides: {e}")

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


# --- Helper functions ---
def fetch_listings():
    api_client = PriceLabsAPI()
    listings = api_client.get_listings()
    active_listings = [
        l for l in listings
        if not l.get('isHidden', True) and l.get('push_enabled', False)
    ]
    return active_listings

def batch_update(listings, increase, batch_size=20, delay=2):
    results = []
    total = len(listings)
    for i in range(0, total, batch_size):
        batch = listings[i:i+batch_size]
        st.info(f"Processing batch {i//batch_size+1} of {(total+batch_size-1)//batch_size} ({len(batch)} listings)")
        for listing in batch:
            try:
                api_client = PriceLabsAPI()
                overrides = api_client.get_listing_overrides(listing['id'], pms=listing.get('pms'))
                adjusted_overrides = []
                for override in overrides.get('overrides', []):
                    if override.get('price_type') != 'fixed':
                        continue
                    if not _is_date_in_valid_range(override.get('date', '')):
                        continue
                    old_price = float(override.get('price', 0))
                    if old_price <= 0:
                        continue
                    new_price = calculate_adjusted_price(old_price, increase=increase)
                    adjusted_overrides.append({
                        'date': override['date'],
                        'price': str(int(new_price)),
                        'price_type': 'fixed',
                        'currency': override.get('currency', 'USD'),
                        'min_stay': override.get('min_stay', 1)
                    })
                if adjusted_overrides:
                    api_client.update_listing_overrides(listing['id'], adjusted_overrides, pms=listing.get('pms'))
                    results.append({
                        'id': listing['id'],
                        'name': listing['name'],
                        'status': 'success'
                    })
            except Exception as e:
                results.append({
                    'id': listing['id'],
                    'name': listing['name'],
                    'status': 'error',
                    'message': str(e)
                })
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
    with st.expander(f"Select listings to adjust ({n_selected} selected)", expanded=False):
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
            
            # Calculate totals
            successful = len([r for r in results if r['status'] == 'success'])
            failed = len([r for r in results if r['status'] == 'error'])
            total = len(results)
            
            st.subheader("Results")
            
            # Summary stats
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Processed", total)
            with col2:
                st.metric("Successful", successful, delta=f"+{successful}")
            with col3:
                st.metric("Failed", failed, delta=f"-{failed}")
            
            # Individual results
            for result in results:
                if result['status'] == 'success':
                    st.success(f"✅ {result['name']}: Updated successfully")
                else:
                    st.error(f"❌ {result['name']}: {result['message']}")
else:
    st.info('Click "Refresh Listings from PriceLabs" to begin.') 