def validate_override(override):
    """Validate override data structure and values"""
    required_fields = ["date", "price", "price_type"]
    if not all(field in override for field in required_fields):
        return False
        
    if override["price_type"] not in ["fixed", "percent"]:
        return False
        
    return True 

def validate_price_type(price_type):
    """Validate price type"""
    return price_type in ["fixed", "percent"]

def validate_price_value(price, price_type):
    """Validate price value based on type"""
    try:
        price_float = float(price)
        if price_type == "fixed":
            return price_float > 0
        elif price_type == "percent":
            return -75 <= price_float <= 500
        return False
    except ValueError:
        return False 