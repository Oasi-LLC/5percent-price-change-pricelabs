from pricelabs_tool.adjustment import compute_listing_adjustments
from pricelabs_tool.bookings import is_booked_status, parse_multi_unit_occupancy, should_skip_booked_date


def test_is_booked_status():
    assert is_booked_status("Booked") is True
    assert is_booked_status("Booked (Check-In)") is True
    assert is_booked_status("") is False
    assert is_booked_status(None) is False


def test_should_skip_booked_date_single_unit():
    assert should_skip_booked_date("Booked", total_units=1) is True
    assert should_skip_booked_date("", total_units=1) is False


def test_should_skip_booked_date_multi_unit_partial_booking():
    assert should_skip_booked_date("Booked", total_units=9) is False
    assert should_skip_booked_date("Booked", total_units=9, multi_unit_occupancy="5/8") is False
    assert should_skip_booked_date("Booked (Check-In)", total_units=5, multi_unit_occupancy="1/5") is False


def test_should_skip_booked_date_multi_unit_fully_sold_out():
    assert should_skip_booked_date("Booked", total_units=9, available=False) is True
    assert should_skip_booked_date("Booked", total_units=2, multi_unit_occupancy="2/2") is True
    assert should_skip_booked_date("Booked (Check-In)", total_units=9, multi_unit_occupancy="8/8") is True
    assert should_skip_booked_date("Booked", total_units=9, multi_unit_occupancy="5/8") is False
    assert should_skip_booked_date("", total_units=9, multi_unit_occupancy="0/0") is False


def test_parse_multi_unit_occupancy():
    assert parse_multi_unit_occupancy("5/8") == (5, 8)
    assert parse_multi_unit_occupancy(" 2 / 2 ") == (2, 2)
    assert parse_multi_unit_occupancy("0/0") == (0, 0)
    assert parse_multi_unit_occupancy(None) is None


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
        "2026-07-01": {"booking_status": "Booked"},
        "2026-07-02": {"booking_status": ""},
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


def test_compute_listing_adjustments_skips_single_unit_booked_only():
    listing = {"id": "316005___633307", "name": "Greenhouse ADA"}
    overrides = [
        {
            "date": "2026-07-04",
            "price": "793",
            "price_type": "fixed",
            "currency": "USD",
            "min_stay": 1,
        },
    ]
    prop_config = {
        "wb1": {
            "name": "Onera Wimberley",
            "listings": [
                {"id": "316005___633307", "units": 1, "batna": 169.00},
            ],
        }
    }
    result = compute_listing_adjustments(
        listing,
        overrides,
        prop_config,
        increase=True,
        booking_by_date={"2026-07-04": {"booking_status": "Booked"}},
    )
    assert result["would_update"] == 0
    assert result["skipped"]["booked"] == 1


def test_compute_listing_adjustments_does_not_skip_multi_unit_partial_booking():
    listing = {"id": "316005___633306", "name": "Greenhouse"}
    overrides = [
        {
            "date": "2026-07-04",
            "price": "808",
            "price_type": "fixed",
            "currency": "USD",
            "min_stay": 1,
        },
    ]
    prop_config = {
        "wb1": {
            "name": "Onera Wimberley",
            "listings": [
                {"id": "316005___633306", "units": 9, "batna": 169.00},
            ],
        }
    }
    result = compute_listing_adjustments(
        listing,
        overrides,
        prop_config,
        increase=True,
        booking_by_date={"2026-07-04": {"booking_status": "Booked"}},
    )
    assert result["would_update"] == 1
    assert result["skipped"]["booked"] == 0
    assert result["adjusted_overrides"][0]["price"] == "848"
