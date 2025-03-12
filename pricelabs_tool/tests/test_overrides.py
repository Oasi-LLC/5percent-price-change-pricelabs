def test_override_updates():
    api = PriceLabsAPI()
    listing_id = "test_listing_id"
    
    # Get current overrides
    current = api.get_listing_overrides(listing_id)
    
    # Update prices
    result = api.update_listing_prices(listing_id, current["overrides"], increase=True)
    
    assert result is not None
    assert "overrides" in result
    
    # Verify price adjustments
    for i, override in enumerate(result["overrides"]):
        if "price" in override:
            original_price = float(current["overrides"][i]["price"])
            new_price = float(override["price"])
            if override["price_type"] == "fixed":
                assert new_price == original_price * 1.05 