import streamlit as st
import time
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv('PRICELABS_API_KEY')
BASE_URL = os.getenv('API_BASE_URL', 'https://api.pricelabs.co/v1')
ADJUSTMENT_PERCENTAGE = 5  # 5% adjustment

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

# --- Helper functions ---
def fetch_listings():
    api_client = PriceLabsAPI()
    listings = api_client.get_listings()
    active_listings = [
        l for l in listings
        if not l.get('isHidden', True) and l.get('push_enabled', False)
    ]
    return active_listings

def batch_update(listings, increase, dry_run, batch_size=20, delay=2):
    results = []
    dry_run_summary = []
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
                    if override.get('price_type') == 'fixed':
                        old_price = float(override.get('price', 0))
                        if old_price > 0:
                            new_price = calculate_adjusted_price(old_price, increase=increase)
                            adjusted_overrides.append({
                                'date': override['date'],
                                'price': str(int(new_price)),
                                'price_type': 'fixed',
                                'currency': override.get('currency', 'USD'),
                                'min_stay': override.get('min_stay', 1)
                            })
                if dry_run:
                    sorted_overrides = sorted(
                        [o for o in overrides.get('overrides', []) if o.get('price_type') == 'fixed'],
                        key=lambda x: x['date']
                    )
                    price_changes = []
                    for override in sorted_overrides[:5]:
                        old_price = float(override.get('price', 0))
                        if old_price > 0:
                            new_price = calculate_adjusted_price(old_price, increase=increase)
                            price_changes.append({
                                'date': override['date'],
                                'old_price': old_price,
                                'new_price': new_price,
                                'currency': override.get('currency', 'USD')
                            })
                    dry_run_summary.append({
                        'id': listing['id'],
                        'name': listing['name'],
                        'changes': len(adjusted_overrides),
                        'price_changes': price_changes
                    })
                else:
                    if adjusted_overrides:
                        api_client.update_listing_overrides(listing['id'], adjusted_overrides, pms=listing.get('pms'))
                        results.append({
                            'id': listing['id'],
                            'name': listing['name'],
                            'status': 'success'
                        })
            except Exception as e:
                if dry_run:
                    dry_run_summary.append({
                        'id': listing['id'],
                        'name': listing['name'],
                        'changes': 0,
                        'error': str(e)
                    })
                else:
                    results.append({
                        'id': listing['id'],
                        'name': listing['name'],
                        'status': 'error',
                        'message': str(e)
                    })
        if i + batch_size < total:
            time.sleep(delay)
    return (results, dry_run_summary)

# --- Streamlit UI ---
st.set_page_config(page_title="PriceLabs Price Adjustment", layout="centered")
st.title("PriceLabs Price Adjustment Tool")

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
    st.subheader("Select Listings to Adjust")
    
    # Create a list of listing names for selection
    listing_options = [f"{listing['name']} (ID: {listing['id']})" for listing in listings]
    selected_listings = st.multiselect(
        "Choose listings to adjust:",
        listing_options,
        default=listing_options  # Select all by default
    )
    
    # Get the actual listing objects for selected items
    selected_listing_objects = []
    for option in selected_listings:
        listing_id = option.split("(ID: ")[1].rstrip(")")
        for listing in listings:
            if str(listing['id']) == listing_id:
                selected_listing_objects.append(listing)
                break
    
    if selected_listing_objects:
        st.subheader("Adjustment Options")
        
        # Adjustment type
        adjustment_type = st.radio(
            "Choose adjustment type:",
            ["Increase by 5%", "Decrease by 5%"]
        )
        increase = adjustment_type == "Increase by 5%"
        
        # Dry run option
        dry_run = st.checkbox("Dry run (preview changes without applying)", value=True)
        
        # Apply button
        if st.button("Apply Price Adjustments", type="primary"):
            if dry_run:
                st.info("Running dry run to preview changes...")
                results, dry_run_summary = batch_update(selected_listing_objects, increase, dry_run=True)
                
                # Calculate dry run totals
                total_changes = sum([item.get('changes', 0) for item in dry_run_summary if 'error' not in item])
                total_listings = len(dry_run_summary)
                successful_dry_run = len([item for item in dry_run_summary if 'error' not in item])
                failed_dry_run = len([item for item in dry_run_summary if 'error' in item])
                
                st.subheader("Dry Run Results")
                
                # Summary stats for dry run
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Listings Processed", total_listings)
                with col2:
                    st.metric("Successful", successful_dry_run, delta=f"+{successful_dry_run}")
                with col3:
                    st.metric("Failed", failed_dry_run, delta=f"-{failed_dry_run}")
                with col4:
                    st.metric("Total Price Changes", total_changes)
                
                # Individual results
                for item in dry_run_summary:
                    if 'error' in item:
                        st.error(f"❌ {item['name']}: {item['error']}")
                    else:
                        st.success(f"✅ {item['name']}: {item['changes']} price changes")
                        if item['price_changes']:
                            st.write("Sample changes:")
                            for change in item['price_changes'][:3]:  # Show first 3
                                st.write(f"  {change['date']}: ${change['old_price']:.0f} → ${change['new_price']:.0f}")
                
                # Show actual apply button after dry run
                if st.button("Apply Changes (after dry run)"):
                    st.info("Applying changes...")
                    results, _ = batch_update(selected_listing_objects, increase, dry_run=False)
                    
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
                st.info("Applying changes directly...")
                results, _ = batch_update(selected_listing_objects, increase, dry_run=False)
                
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