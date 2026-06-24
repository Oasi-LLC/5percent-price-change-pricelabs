from pricelabs_tool.adjustment import compute_listing_adjustments
from pricelabs_tool.bookings import is_booked_status


def test_is_booked_status():
    assert is_booked_status("Booked") is True
    assert is_booked_status("Booked (Check-In)") is True
    assert is_booked_status("") is False
    assert is_booked_status(None) is False


def test_compute_listing_adjustments_skips_booked_dates():
    listing = {"id": "123", "name": "Test"}
    overrides = [
        {
            "date": "2026-07-01",
            "price": "200",
            "price_type": "fixed",
            "currency": "USD",
            "min_stay": 1,
        },
        {
            "date": "2026-07-02",
            "price": "200",
            "price_type": "fixed",
            "currency": "USD",
            "min_stay": 1,
        },
    ]
    booking_by_date = {
        "2026-07-01": "Booked",
        "2026-07-02": "",
    }
    result = compute_listing_adjustments(
        listing,
        overrides,
        {},
        increase=True,
        booking_by_date=booking_by_date,
    )
    assert result["would_update"] == 1
    assert result["skipped"]["booked"] == 1
    assert result["adjusted_overrides"][0]["date"] == "2026-07-02"
