def test_full_adjustment_workflow():
    """Test complete price adjustment workflow"""
    api = PriceLabsAPI()
    listing_id = "test_listing_id"
    
    # Initial state
    initial = api.get_listing_overrides(listing_id)
    
    # Increase prices
    increased = api.update_listing_prices(listing_id, initial["overrides"], increase=True)
    
    # Decrease prices
    decreased = api.update_listing_prices(listing_id, increased["overrides"], increase=False)
    
    # Verify final state matches initial
    assert_overrides_match(initial["overrides"], decreased["overrides"]) 