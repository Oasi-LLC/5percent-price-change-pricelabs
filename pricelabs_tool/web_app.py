from flask import Flask, render_template, jsonify, request
from .api_client import PriceLabsAPI
from .price_calculator import calculate_adjusted_price
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, 
            template_folder='web/templates',
            static_folder='web/static')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/listings')
def get_listings():
    try:
        api_client = PriceLabsAPI()
        listings = api_client.get_listings()
        active_listings = [
            listing for listing in listings
            if not listing.get('isHidden', True) 
            and listing.get('push_enabled', False)
        ]
        return jsonify({
            'status': 'success',
            'listings': active_listings
        })
    except Exception as e:
        logger.error(f"Error getting listings: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/update-prices', methods=['POST'])
def update_prices():
    try:
        data = request.json
        increase = data.get('increase', False)
        dry_run = data.get('dry_run', False)
        listing_ids = data.get('listing_ids', [])
        
        api_client = PriceLabsAPI()
        listings = api_client.get_listings()
        
        # Filter listings
        active_listings = [
            listing for listing in listings
            if not listing.get('isHidden', True) 
            and listing.get('push_enabled', False)
        ]
        if listing_ids:
            active_listings = [l for l in active_listings if str(l.get('id')) in listing_ids]
        
        # Process each listing
        results = []
        dry_run_summary = []
        for listing in active_listings:
            try:
                # Get current overrides
                overrides = api_client.get_listing_overrides(
                    listing['id'], 
                    pms=listing.get('pms')
                )
                
                # Calculate new prices
                adjusted_overrides = []
                for override in overrides.get('overrides', []):
                    if override.get('price_type') == 'fixed':
                        old_price = float(override.get('price', 0))
                        if old_price > 0:
                            new_price = calculate_adjusted_price(
                                old_price, 
                                increase=increase
                            )
                            adjusted_overrides.append({
                                'date': override['date'],
                                'price': str(int(new_price)),
                                'price_type': 'fixed',
                                'currency': override.get('currency', 'USD'),
                                'min_stay': override.get('min_stay', 1)
                            })
                
                if dry_run:
                    # Sort overrides by date and get first 5 dates with their prices
                    sorted_overrides = sorted(
                        [o for o in overrides.get('overrides', []) if o.get('price_type') == 'fixed'],
                        key=lambda x: x['date']
                    )
                    price_changes = []
                    for override in sorted_overrides[:5]:  # Only first 5 earliest dates
                        old_price = float(override.get('price', 0))
                        if old_price > 0:
                            new_price = calculate_adjusted_price(
                                old_price, 
                                increase=increase
                            )
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
                    # Update prices
                    if adjusted_overrides:
                        api_client.update_listing_overrides(
                            listing['id'],
                            adjusted_overrides,
                            pms=listing.get('pms')
                        )
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
        
        if dry_run:
            return jsonify({
                'status': 'success',
                'summary': dry_run_summary
            })
        else:
            return jsonify({
                'status': 'success',
                'results': results
            })
    except Exception as e:
        logger.error(f"Error updating prices: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001) 