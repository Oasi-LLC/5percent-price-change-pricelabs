def test_price_adjustments():
    test_cases = [
        {"current": "100", "type": "fixed", "increase": True, "expected": "105.00"},
        {"current": "100", "type": "fixed", "increase": False, "expected": "95.00"},
        {"current": "10", "type": "percent", "increase": True, "expected": "15.00"},
        {"current": "10", "type": "percent", "increase": False, "expected": "5.00"}
    ]
    
    for case in test_cases:
        result = calculate_adjusted_price(case["current"], case["type"], case["increase"])
        assert str(result) == case["expected"] 