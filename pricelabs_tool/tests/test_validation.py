def test_override_validation():
    valid_override = {
        "date": "2024-03-20",
        "price": "100",
        "price_type": "fixed",
        "currency": "EUR"
    }
    assert validate_override(valid_override) is True
    
    invalid_override = {
        "date": "2024-03-20",
        "price_type": "invalid"
    }
    assert validate_override(invalid_override) is False 