import streamlit as st
import time
from api_client import PriceLabsAPI
from price_calculator import calculate_adjusted_price

st.set_page_config(page_title="PriceLabs Price Adjustment", layout="centered")
st.title("PriceLabs Price Adjustment Tool")

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

# --- UI ---
if 'listings' not in st.session_state:
    st.session_state['listings'] = []

if st.button('Refresh Listings from PriceLabs'):
    with st.spinner('Fetching latest listings...'):
        st.session_state['listings'] = fetch_listings()
        st.success(f"Fetched {len(st.session_state['listings'])} active listings.")

listings = st.session_state['listings']

if listings:
    all_ids = [str(l['id']) for l in listings]
    all_names = [f"{l['name']} ({l['id']})" for l in listings]
    id_to_name = {str(l['id']): l['name'] for l in listings}
    
    selected_ids = st.multiselect(
        'Select Listings',
        options=all_ids,
        default=all_ids,
        format_func=lambda x: id_to_name.get(x, x)
    )
    selected_listings = [l for l in listings if str(l['id']) in selected_ids]
    
    col1, col2 = st.columns(2)
    with col1:
        adj = st.radio('Adjustment', ['Increase by 5%', 'Decrease by 5%'])
    with col2:
        dry_run = st.checkbox('Dry Run (Preview only)', value=True)
    
    if st.button('Apply Changes'):
        if not selected_listings:
            st.warning('Please select at least one listing.')
        else:
            increase = adj == 'Increase by 5%'
            with st.spinner('Processing...'):
                results, dry_run_summary = batch_update(selected_listings, increase, dry_run)
            if dry_run:
                st.subheader('Dry Run Summary')
                for summary in dry_run_summary:
                    st.markdown(f"**{summary['name']}** ({summary['id']}) - {summary['changes']} changes")
                    for pc in summary.get('price_changes', []):
                        st.write(f"{pc['date']}: {pc['old_price']} → {pc['new_price']} {pc['currency']}")
                    if 'error' in summary:
                        st.error(f"Error: {summary['error']}")
            else:
                st.subheader('Results')
                for res in results:
                    if res['status'] == 'success':
                        st.success(f"{res['name']} ({res['id']}) updated successfully.")
                    else:
                        st.error(f"{res['name']} ({res['id']}): {res.get('message', 'Unknown error')}")
else:
    st.info('Click "Refresh Listings from PriceLabs" to begin.') 