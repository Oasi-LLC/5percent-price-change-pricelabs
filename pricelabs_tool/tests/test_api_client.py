"""Tests for PriceLabs API client booking-status batch handling."""

from unittest.mock import MagicMock, patch

from pricelabs_tool.api_client import PriceLabsAPI


def test_booking_status_batch_continues_when_one_listing_errors():
    listings = [
        {"id": "467334", "pms": "hostaway"},
        {"id": "4140___8114", "pms": "resnexus"},
    ]
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [
        {
            "id": "467334",
            "error": "Listing data does not exist in PriceLabs",
        },
        {
            "id": "4140___8114",
            "data": [
                {"date": "2026-07-01", "booking_status": "Booked"},
                {"date": "2026-07-02", "booking_status": ""},
            ],
        },
    ]

    with patch.dict("os.environ", {"PRICELABS_API_KEY": "test-key"}):
        client = PriceLabsAPI()
    client.session.post = MagicMock(return_value=mock_response)

    result = client.get_booking_status_by_listing(listings)

    assert result["467334"] == {}
    assert result["4140___8114"]["2026-07-01"] == "Booked"
    assert result["4140___8114"]["2026-07-02"] == ""
