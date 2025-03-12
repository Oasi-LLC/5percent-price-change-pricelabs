from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from .config import ADJUSTMENT_PERCENTAGE, DEFAULT_CURRENCY

logger = logging.getLogger(__name__)

def get_date_range(start_date: Optional[datetime] = None, days: int = 30) -> List[str]:
    """
    Generate a list of dates in YYYY-MM-DD format
    
    Args:
        start_date: Starting date (defaults to tomorrow)
        days: Number of days to generate
    
    Returns:
        List of date strings
    """
    if not start_date:
        start_date = datetime.now() + timedelta(days=1)
    
    dates = []
    for i in range(days):
        date = start_date + timedelta(days=i)
        dates.append(date.strftime("%Y-%m-%d"))
    return dates

def calculate_adjusted_price(price: float, increase: bool = True) -> float:
    """
    Calculate adjusted price based on percentage and round to integer
    
    Args:
        price: Current price
        increase: Whether to increase or decrease
    
    Returns:
        Adjusted price as integer
    """
    adjustment = 1 + (ADJUSTMENT_PERCENTAGE / 100 * (1 if increase else -1))
    return round(price * adjustment)  # Round to integer instead of 2 decimal places

def calculate_adjusted_prices(
    current_overrides: Dict,
    increase: bool = True,
    decrease: bool = False,
    start_date: Optional[datetime] = None,
    days: Optional[int] = None,
    base_price: Optional[float] = None
) -> List[Dict]:
    """
    Calculate adjusted prices for existing overrides
    
    Args:
        current_overrides: Current price overrides from PriceLabs
        increase: Whether to increase prices
        decrease: Whether to decrease prices
        start_date: Optional starting date for filtering overrides
        days: Optional number of days to adjust (only used if start_date is provided)
        base_price: Not used - kept for backwards compatibility
    
    Returns:
        List of adjusted price overrides
    """
    # Get all existing fixed-price overrides
    existing_overrides = [
        override for override in current_overrides.get('overrides', [])
        if override.get('price_type') == 'fixed'
    ]
    
    if not existing_overrides:
        logger.info("No existing overrides found to adjust")
        return []
    
    # Log override date range
    override_dates = sorted(o['date'] for o in existing_overrides)
    logger.info(f"Found {len(existing_overrides)} existing overrides from {override_dates[0]} to {override_dates[-1]}")
    
    # Filter by date range if start_date is provided
    if start_date:
        end_date = start_date + timedelta(days=days) if days else None
        existing_overrides = [
            override for override in existing_overrides
            if datetime.strptime(override['date'], "%Y-%m-%d") >= start_date
            and (not end_date or datetime.strptime(override['date'], "%Y-%m-%d") < end_date)
        ]
        if existing_overrides:
            filtered_dates = sorted(o['date'] for o in existing_overrides)
            logger.info(f"Filtered to {len(existing_overrides)} overrides from {filtered_dates[0]} to {filtered_dates[-1]}")
    
    # Determine whether to increase or decrease
    should_increase = increase and not decrease
    
    adjusted_overrides = []
    for override in existing_overrides:
        current_price = float(override['price'])
        if current_price > 0:
            adjusted_price = calculate_adjusted_price(current_price, should_increase)
            
            # Create new override with adjusted price
            adjusted_override = {
                'date': override['date'],
                'price': str(adjusted_price),
                'price_type': 'fixed',
                'currency': override.get('currency', DEFAULT_CURRENCY),
                'min_stay': override.get('min_stay', 2)
            }
            
            adjusted_overrides.append(adjusted_override)
            logger.debug(f"Adjusted price for {override['date']}: {current_price} -> {adjusted_price}")
    
    return adjusted_overrides 