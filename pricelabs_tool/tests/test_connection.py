def test_api_authentication():
    api = PriceLabsAPI()
    listing_id = "test_listing_id"
    response = api.get_listing_overrides(listing_id)
    assert response is not None
    assert "overrides" in response 