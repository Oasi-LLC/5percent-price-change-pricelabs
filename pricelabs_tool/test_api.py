from api_client import PriceLabsAPI

def test_price_adjustment():
    api = PriceLabsAPI()
    listing_id = "YOUR_LISTING_ID"  # Replace with actual listing ID
    
    # Get current overrides
    current_overrides = api.get_listing_overrides(listing_id)
    if current_overrides is None:
        print("❌ Failed to fetch current overrides")
        return
    
    print("✅ Successfully fetched current overrides")
    print(f"Current data: {current_overrides}")
    
    # Update prices with 5% increase
    result = api.update_listing_prices(
        listing_id,
        current_overrides['overrides'],
        increase=True
    )
    
    if result is None:
        print("❌ Failed to update prices")
    else:
        print("✅ Successfully updated prices")
        print(f"Updated data: {result}")

if __name__ == "__main__":
    test_price_adjustment() 